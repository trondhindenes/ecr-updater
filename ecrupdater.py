import sys
import os
import json
import time
import base64
import boto3
import logging
import logging.config
from kubernetes import client as k8sclient
from kubernetes.client import Configuration, ApiClient, ApiException


def setup_logging(
        log_config_file=os.environ.get('LOG_CONFIG', './logging.json'),
        # fallback if no logger config file has been configured
        default_level=os.environ.get('LOG_LEVEL', 'INFO')
):
    if os.path.exists(log_config_file):
        print("Loading log configuration file from path '{}'...".format(log_config_file))
        with open(log_config_file, 'rt') as f:
            config = json.load(f)
        logging.config.dictConfig(config)
    else:
        print("No Log config file provided, loading default configuration.")
        logging.basicConfig(level=default_level)


def exception_handler(exception_type, exception, traceback):
    # Removes standard python stacktrace in case of exceptions
    logger.warning("%s: %s", exception_type.__name__, exception)


# Custom exception hook to hide traceback info from logs
if not os.getenv('CDV2_DEBUG_ENABLED') == 'TRUE':
    sys.excepthook = exception_handler


print('Starting ECR-updater ..')
pull_secret_name = os.getenv('K8S_PULL_SECRET_NAME', None)
env_update_interval = os.getenv('ECR_UPDATE_INTERVAL', '3600')
create_missing_pull_secrets_str = os.getenv('ECR_CREATE_MISSING', 'false')
# Allows the kubernetes python clients to talk to k8s via the kubectl-proxy sidecar container
kubernetes_api_endpoint = os.getenv('KUBERNETES_API_ENDPOINT', 'http://localhost:8001')

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
    k8s_api_client = ApiClient(configuration=k8s_config)
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
            logger.info('Creating secret %s in namespace %s', pull_secret_name, namespace.metadata.name)
            try:
                v1.create_namespaced_secret(namespace.metadata.name, secret_body)
            except ApiException:
                logger.exception('Could not create secret %s in namespace %s',
                                 pull_secret_name,
                                 namespace.metadata.name)


def update_ecr():
    logger.info('Starting ECR secret update loop ..')
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
    k8s_api_client = ApiClient(configuration=k8s_config)
    v1 = k8sclient.CoreV1Api(api_client=k8s_api_client)
    secrets = v1.list_secret_for_all_namespaces()

    registry_secrets = [x for x in secrets.items if x.metadata.name == pull_secret_name]
    logger.info('Found %s registry_secrets matching name %s', len(registry_secrets), pull_secret_name)
    for secret in registry_secrets:
        secret_name = secret.metadata.name
        if secret.type == 'kubernetes.io/dockercfg':
            logger.info('Updating secret %s (type kubernetes.io/dockercfg) in namespace %s',
                        secret_name,
                        secret.metadata.namespace)
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
            logger.info('Updating secret %s (type kubernetes.io/dockerconfigjson) in namespace %s',
                        secret_name,
                        secret.metadata.namespace)
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
            logger.warning('Unknown secret type for secret name %s: %s'.format(secret_name, secret.type))


if __name__ == '__main__':
    setup_logging()
    logger = logging.getLogger(__name__)
    while True:
        logger.info('Running credentials update loop ..')
        create_pull_secrets()
        update_ecr()
        logger.info(f'...done. Waiting %s seconds', update_interval)
        time.sleep(update_interval)
