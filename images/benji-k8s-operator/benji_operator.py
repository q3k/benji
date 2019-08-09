import copy
import random
import string

import kopf
import kubernetes
import yaml
from concurrent.futures.thread import ThreadPoolExecutor

from typing import List, Any, Dict

SERVICE_NAMESPACE_FILENAME = '/var/run/secrets/kubernetes.io/serviceaccount/namespace'

kubernetes.config.load_incluster_config()

version_recon_executor = ThreadPoolExecutor(max_workers=1)

# Try to load the configuration for this operator
custom_objects_api = kubernetes.client.CustomObjectsApi()
operator_config = custom_objects_api.get_custom_object(group='benji-backup.me',
                                                       version='v1alpha1',
                                                       plural='benjioperatorconfigs',
                                                       name='benji')


def service_account_namespace(_namespace=None) -> str:
    if _namespace is None:
        with open(SERVICE_NAMESPACE_FILENAME, 'r') as f:
            _namespace = f.read()
            if _namespace == '':
                raise RuntimeError(f'{SERVICE_NAMESPACE_FILENAME} is empty.')
    return _namespace


def _random_string(length: int) -> str:
    return ''.join(random.choices(string.ascii_lowercase + string.digits, k=length))


def create_job(command: List[str], *, owner_body: Dict[str, Any]) -> kubernetes.client.models.v1_job.V1Job:
    job_manifest = copy.deepcopy(operator_config['spec']['jobTemplate'])
    job_manifest['spec']['template']['spec']['containers'][0]['command'] = command

    # Make it our child: assign the namespace, name, labels, owner references, etc.
    kopf.adopt(job_manifest, owner=owner_body)

    # Actually create the job via the Kubernetes API.
    batch_v1_api = kubernetes.client.BatchV1Api()
    return batch_v1_api.create_namespaced_job(namespace=service_account_namespace(), body=job_manifest)


def create_cron_job(command: List[str], schedule: str, *,
                    owner_body: Dict[str, Any]) -> kubernetes.client.models.v1_job.V1Job:
    cronjob_manigest = copy.deepcopy(operator_config['spec']['cronJobTemplate'])
    cronjob_manigest['spec']['schedule'] = schedule
    cronjob_manigest['spec']['jobTemplate']['spec']['template']['containers'][0]['command'] = command

    # Make it our child: assign the namespace, name, labels, owner references, etc.
    kopf.adopt(cronjob_manigest, owner=owner_body)

    # Actually create the job via the Kubernetes API.
    batch_v1_api = kubernetes.client.BatchV1Api()
    return batch_v1_api.create_namespaced_job(namespace=service_account_namespace(), body=cronjob_manigest)


@kopf.on.create('benji-backup.me', 'v1alpha1', 'benjirestores')
def benji_restore_pvc(body, **kwargs):

    cr_namespace = body['metadata']['namespace']
    cr_name = body['metadata']['name']
    pvc_name = body['spec']['persistentVolumeClaim']['claimName']
    version_name = body['spec']['version']['versionName']

    command = [
        'benji-restore-pvc',
        version_name,
        cr_namespace,
        pvc_name,
    ]

    job = create_job(command, owner_body=body)

    # Update the parent's status.
    return {
        'associatedJobs': [{
            'namespace': job.metadata.namespace,
            'name': job.metadata.name,
            'uid': job.metadata.uid,
        }]
    }


@kopf.on.update('benji-backup.me', 'v1alpha1', 'benjiversions')
def benji_version_reconciliation(body, **kwargs):
    pass


@kopf.on.delete('benji-backup.me', 'v1alpha1', 'benjiversions')
def benji_version_reconciliation(body, **kwargs):
    pass
