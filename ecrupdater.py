import os
import json
import time
import base64
import boto3
from kubernetes import client as k8sclient
from kubernetes.client import Configuration, ApiClient

print("starting the thing")

pull_secret_name = os.getenv('K8S_PULL_SECRET_NAME', None)
env_update_interval = os.getenv('ECR_UPDATE_INTERVAL', '3600')

try:
    update_interval = int(env_update_interval)
except:
    raise ValueError(str.format('unable to parse {0} into seconds, exiting', env_update_interval))

if pull_secret_name is None:
    raise ValueError('Specify name of secret in env variable K8S_PULL_SECRET_NAME')


def update_ecr():
    print('starting update loop')
    client = boto3.client('ecr')
    response = client.get_authorization_token()
    token = response['authorizationData'][0]['authorizationToken']
    server = response['authorizationData'][0]['proxyEndpoint']
    decoded_token = base64.b64decode(token)
    registry_username = decoded_token.split(':')[0]
    registry_password = decoded_token.split(':')[1]

    k8sconfig = Configuration()
    k8sconfig.host = "localhost:8001"
    myapiclient = ApiClient(config=k8sconfig)
    v1 = k8sclient.CoreV1Api(api_client=myapiclient)
    secrets = v1.list_secret_for_all_namespaces()

    

    registry_secrets = [x for x in secrets._items if x.metadata.name == pull_secret_name]
    print('pull secret name to search for: ' + pull_secret_name)
    print('found {} registry_secrets matching name'.format(str(len(registry_secrets))))
    for secret in registry_secrets:
        k8s_secret = {server:
                        {
                            "username": registry_username,
                            "password": registry_password
                        }
                    }
        body = {
            "kind": "Secret",
            "apiVersion": "v1",
            "metadata": {
                "name": "ecr",
                "creationTimestamp": None
            },
            "data": {
                ".dockercfg": base64.b64encode(bytes(json.dumps(k8s_secret)), 'utf-8')
            },
            "type": "kubernetes.io/dockercfg"
        }
        res = v1.patch_namespaced_secret(secret.metadata.name, secret.metadata.namespace, body)


if __name__ == '__main__':
    print("Sleeping on first startup")
    time.sleep(5)
    while True:
        print("Running update loop")
        update_ecr()
        print(str.format("...done. Waiting {0} seconds", str(update_interval)))
        time.sleep(update_interval)

