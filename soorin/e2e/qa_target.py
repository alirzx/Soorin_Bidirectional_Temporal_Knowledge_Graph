"""Read-only Docker inventory gate for future disposable QA execution."""
import json
import subprocess
import urllib.parse

PROJECT = 'soorin-tkg-v1-qa'


def verify_qa_target(base_url, project, *, inspect=None):
    """Require the opted-in project, loopback binding and project-owned volumes.

    Never starts/stops a container. Port selection alone cannot prove isolation.
    Operator must recheck port/container ownership immediately before execution.
    """
    parsed = urllib.parse.urlsplit(base_url)
    if project != PROJECT or parsed.hostname != '127.0.0.1' or parsed.port in {1516, 2516}:
        raise ValueError('disposable_qa_target_required')
    if inspect is None:
        def inspect(service):
            result = subprocess.run(['docker', 'ps', '-q', '--filter', f'label=com.docker.compose.project={project}',
                '--filter', f'label=com.docker.compose.service={service}'], check=True, capture_output=True, timeout=5)
            ids = result.stdout.decode().split()
            if len(ids) != 1:
                raise ValueError('qa_service_not_unique')
            result = subprocess.run(['docker', 'inspect', ids[0]], check=True, capture_output=True, timeout=5)
            return json.loads(result.stdout)[0]
    for service, destination, container_port in [('app', '/app/data', '1516/tcp'), ('db', '/var/lib/postgresql/data', '5432/tcp')]:
        row = inspect(service)
        labels = row.get('Config', {}).get('Labels', {})
        if (labels.get('com.docker.compose.project') != project
                or labels.get('com.docker.compose.service') != service
                or not row.get('State', {}).get('Running')):
            raise ValueError('qa_container_ownership_mismatch')
        mounts = [m for m in row.get('Mounts', []) if m.get('Destination') == destination]
        if len(mounts) != 1 or mounts[0].get('Type') != 'volume' or mounts[0].get('Name') != f'{project}_soorin_sprint1_{"data" if service == "app" else "db"}':
            raise ValueError('qa_volume_ownership_mismatch')
        bindings = row.get('NetworkSettings', {}).get('Ports', {}).get(container_port) or []
        if len(bindings) != 1 or bindings[0].get('HostIp') != '127.0.0.1':
            raise ValueError('qa_loopback_binding_required')
        port = int(bindings[0]['HostPort'])
        if port in {1516, 1517, 2516, 2517} or (service == 'app' and port != parsed.port):
            raise ValueError('qa_port_ownership_mismatch')
