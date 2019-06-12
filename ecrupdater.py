import sys
import os
import json
import time
import base64
import boto3
from kubernetes import client as k8sclient
from kubernetes.client import Configuration, ApiClient


def exception_handler(exception_type, exception, traceback):
    # Removes standard python stacktrace in case of exceptions
    print("%s: %s" % (exception_type.__name__, exception))


# Custom exception hook to hide traceback info from logs
if not os.getenv('CDV2_DEBUG_ENABLED') == 'TRUE':
    sys.excepthook = exception_handler


print('starting the thing')
pull_secret_name = os.getenv('K8S_PULL_SECRET_NAME', None)
env_update_interval = os.getenv('ECR_UPDATE_INTERVAL', '3600')
create_missing_pull_secrets_str = os.getenv('ECR_CREATE_MISSING', 'false')
kubernetes_api_endpoint = os.getenv('KUBERNETES_API_ENDPOINT', 'localhost:8001')

try:
    update_interval = int(env_update_interval)
except:
    raise ValueError(f'unable to parse {env_update_interval} into seconds, exiting')

if pull_secret_name is None:
    raise ValueError('Specify name of secret in env variable K8S_PULL_SECRET_NAME')


def create_pull_secrets():
    if create_missing_pull_secrets_str.lower() != 'true':
        return None

    k8s_config = Configuration()
    k8s_config.host = kubernetes_api_endpoint
    k8s_api_client = ApiClient(config=k8s_config)
    v1 = k8sclient.CoreV1Api(api_client=k8s_api_client)
    namespaces = v1.list_namespace()
    for namespace in namespaces.items:
        ns_secrets = v1.list_namespaced_secret(namespace.metadata.name)
        has_ecr_secret = [x for x in ns_secrets.items if x.metadata.name == pull_secret_name]
        if not has_ecr_secret:
            k8s_secret = {
                'server':
                    {
                        'username': 'temp',
                        'password': 'temp'
                    }
            }
            b64_k8s_secret = base64.b64encode(json.dumps(k8s_secret).encode('utf-8')).decode('utf-8')
            secret_body = {
                'kind': 'Secret',
                'apiVersion': 'v1',
                'metadata': {
                    'name': pull_secret_name,
                    'creationTimestamp': None
                },
                'data': {
                    '.dockerconfigjson': b64_k8s_secret
                },
                'type': 'kubernetes.io/dockerconfigjson'
            }
            print(f'Creating secret {pull_secret_name} in namespace {namespace.metadata.name}')
            try:
                v1.create_namespaced_secret(namespace.metadata.name, secret_body)
            except Exception as e:
                print(str(e))


def update_ecr():
    print('starting update loop')
    client = boto3.client('ecr')
    response = client.get_authorization_token()
    token = response['authorizationData'][0]['authorizationToken']
    server = response['authorizationData'][0]['proxyEndpoint']
    bare_server = server.replace('https://', '')
    decoded_token = base64.b64decode(token).decode('utf-8')
    registry_username = decoded_token.split(':')[0]
    registry_password = decoded_token.split(':')[1]

    k8s_config = Configuration()
    k8s_config.host = kubernetes_api_endpoint
    k8s_api_client = ApiClient(config=k8s_config)
    v1 = k8sclient.CoreV1Api(api_client=k8s_api_client)
    secrets = v1.list_secret_for_all_namespaces()

    registry_secrets = [x for x in secrets.items if x.metadata.name == pull_secret_name]
    print(f'pull secret name to search for: {pull_secret_name}')
    print(f'found {len(registry_secrets)} registry_secrets matching name {pull_secret_name}')
    for secret in registry_secrets:
        secret_name = secret.metadata.name
        if secret.type == 'kubernetes.io/dockercfg':
            print(f'Updating secret {secret_name} (type kubernetes.io/dockercfg) in namespace {secret.metadata.namespace}')
            k8s_secret = {
                server:
                    {
                        'username': registry_username,
                        'password': registry_password
                    }
            }

            b64_k8s_secret = base64.b64encode(json.dumps(k8s_secret).encode('utf-8')).decode('utf-8')
            body = {
                'kind': 'Secret',
                'apiVersion': 'v1',
                'metadata': {
                    'name': pull_secret_name,
                    'creationTimestamp': None
                },
                'data': {
                    '.dockercfg': b64_k8s_secret
                },
                'type': 'kubernetes.io/dockercfg'
            }
            res = v1.patch_namespaced_secret(secret.metadata.name, secret.metadata.namespace, body)
        elif secret.type == 'kubernetes.io/dockerconfigjson':
            print(f'Updating secret {secret_name} (type kubernetes.io/dockerconfigjson) in namespace {secret.metadata.namespace}')
            k8s_secret = {
                'auths': {
                    bare_server: {
                        'username': registry_username,
                        'password': registry_password
                    }
                }
            }
            b64_k8s_secret = base64.b64encode(json.dumps(k8s_secret).encode('utf-8')).decode('utf-8')
            body = {
                'kind': 'Secret',
                'apiVersion': 'v1',
                'metadata': {
                    'name': pull_secret_name,
                    'creationTimestamp': None
                },
                'data': {
                    '.dockerconfigjson': b64_k8s_secret
                },
                'type': 'kubernetes.io/dockerconfigjson'
            }
            res = v1.patch_namespaced_secret(secret.metadata.name, secret.metadata.namespace, body)
        else:
            print('Unknown secret type for secret {}: {}'.format(secret_name, secret.type))


if __name__ == '__main__':
    while True:
        print('Running update loop')
        create_pull_secrets()
        update_ecr()
        print(f'...done. Waiting {str(update_interval)} seconds')
        time.sleep(update_interval)
