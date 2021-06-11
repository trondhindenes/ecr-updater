# K8s-Ecrupdater
Because of the way AWS ECR docker registries work, the credentials have to be refreshed.   
This image pulls credentials from ECR every hour, and injects them into Kubernetes so that images can be pulled from a private repo.

This allows the use of AWS ECR registries also when your Kubernetes cluster is running in another cloud provider, or you don't want to set up EC2 roles for it.

Grab container images from: https://cloud.docker.com/u/trondhindenes/repository/docker/trondhindenes/k8s-ecrupdater

## Configuration
Configure with the following environment variables:   
```
K8S_PULL_SECRET_NAME: Name of the Kubernetes pull secret to update   
ECR_UPDATE_INTERVAL: (optional, time in seconds)
ECR_CREATE_MISSING: if this envvar is set to `true`, missing pull secrets will be created in all namespaces
(there's a good chance this will fail on older (pre 1.11) clusters.   
AWS_DEFAULT_REGION: (set to your region)   
AWS_ACCESS_KEY_ID: aws creds   
AWS_SECRET_ACCESS_KEY: aws creds
LOG_CONFIG: optional log config file (defaults to ./logging.json)   
LOG_LEVEL: Applies only if no log config file has been found (defaults to INFO)   
```

Note that if you're using alternate methods of providing the pod with AWS credentials (such as kube2iam or similar) you can skip the `AWS_ACCESS_KEY_ID`/`AWS_SECRET_ACCESS_KEY` configuration items.

## Example deployment
It is assumed that you already have ECR setup, an IAM user with access to it, and that you have `kubectl` configured to communicate with your Kubernetes cluster.

You can also run it locally using `kubectl proxy` on your computer if you want to test things out. In that case, make sure the proxy listens on `localhost:8001`

1. (this step is only required if `ECR_CREATE_MISSING` is not set to true) Create a secret called ecr. This is the secret that this pod will update regularly. It doesn't matter what you put in here, as ecrupdater will update it, it just needs to exist.:
`kubectl create secret docker-registry ecr --docker-username=smash --docker-password=lol --docker-email lol@lol.com`   
NOTE: `ecrupdater` will look for the secrets with the specified name across all your namespaces if you're using the authorization template below. So in this example any secret named `ecr` across all namespaces will be updated. If you want to separate them you can run multiple instances of `ecrupdater`, optionally with tighter (namespaces-isolated) security.

2. Create the authorization stuff that lets kubectl-proxy (running in the same pod as the ecr-updater) interact with kubernetes:
`kubectl apply -f example_deployment/01_authorization.yml`

3. Create a IAM user that has read access to your registries. The access key and secret key need to be base64-encoded (remember to use the `-n` option):   
`echo -n "PUT_ACCESSKEY_HERE" | base64`   
`echo -n "PUT_SECRETKEY_HERE" | base64`   
Put this info in the file `example_deployment/01_aws_credentials.yml.yml` in this repo.   
Now you can create a secret that will hold this info. This is how the ecr updater will log on to AWS:   
`kubectl apply -f example_deployment/01_aws_credentials.yml`

4. Deploy the pod. This contains both the ecr-updater and a "sidecar" container running kubectl-proxy. The proxy allows communication with the kubernetes api in a simple manner.
Make sure to set your correct aws region in `example_deployment/02_deployment.yml` before deploying!
`kubectl apply -f example_deployment/02_deployment.yml`   

5. Test a deployment. Replace the containerimage with one from your own ecr registry, deploy it and prosper! (note that the ecrupdater initially pauses for 60 seconds, so make sure time has passed between the ecr updater pod coming online, and you run the next command)
`kubectl apply -f example_deployment/03_pullsecret_test.yml`

## Logging
By default, the service logs using the built in python logging package and the python-json-logger package for the json formatting.
In order to change the log configuration, the service expects a log config file 'logging.json' in the working directory.
Alternatively, this log config file path can be configured via the ENV variable `LOG_CONFIG` using a configMap.

### Logger config docs
* https://docs.python.org/3/library/logging.config.html

example log config file to enable JSON logging on INFO level.
```
{
  "version": 1,
  "disable_existing_loggers": false,
  "formatters": {
    "json": {
      "format": "%(asctime)s %(levelname)s %(message)s %(pathname)s %(lineno)d %(threadName)s",
      "class": "pythonjsonlogger.jsonlogger.JsonFormatter"
    }
  },
  "handlers": {
    "json": {
      "class": "logging.StreamHandler",
      "formatter": "json"
    }
  },
  "loggers": {
    "": {
      "handlers": ["json"],
      "level": "INFO"
    }
  }
}
``` 
