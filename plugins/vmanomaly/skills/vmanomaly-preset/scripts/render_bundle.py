#!/usr/bin/env python3
"""Assemble a local preset bundle from API artifacts and pinned dashboard inputs.

JSON is emitted as YAML 1.2 for deployment files, avoiding an extra YAML runtime
or text substitution in expressions. No network access or deployment is performed.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
from copy import deepcopy
from pathlib import Path
from typing import Any

MAX_INPUT_BYTES = 8 * 1024 * 1024


def load_json(path: Path, expected_sha256: str | None = None) -> dict[str, Any]:
    with path.open('rb') as stream:
        data = stream.read(MAX_INPUT_BYTES + 1)
    if len(data) > MAX_INPUT_BYTES:
        raise ValueError(f'Input exceeds 8 MiB: {path.name}')
    if expected_sha256 is not None and sha256(data) != expected_sha256:
        raise ValueError(f'Checksum mismatch: {path.name}')
    result = json.loads(data)
    if not isinstance(result, dict):
        raise ValueError(f'Expected JSON object: {path.name}')
    return result


def encode(value: Any) -> str:
    return json.dumps(value, indent=2, ensure_ascii=False, allow_nan=False) + '\n'


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def require_pin(image: str) -> None:
    """Require an explicit tag or SHA-256 digest; registry existence is checked separately."""
    if (
        not isinstance(image, str)
        or re.search(r'\s', image)
        or not re.fullmatch(r'[^@\s]+(?:@sha256:[a-f0-9]{64}|:[A-Za-z0-9_][A-Za-z0-9_.-]{0,127})', image)
        or image.endswith(':latest')
    ):
        raise ValueError('Use explicit image versions or digests, not latest')


def check_credentials(value: Any) -> None:
    """Reject common inline credential fields; this is not a general secret scanner."""
    if isinstance(value, dict):
        for key, item in value.items():
            if (
                key.lower() in {'password', 'bearer_token', 'access_token', 'api_key', 'authorization', 'license_key'}
                and item
            ) or (key.lower() == 'license' and isinstance(item, dict) and item.get('key')):
                raise ValueError('Use file/secret references instead of inline credentials')
            check_credentials(item)
    elif isinstance(value, list):
        for item in value:
            check_credentials(item)
    elif isinstance(value, str) and re.match(r'https?://[^/]*@', value):
        raise ValueError('URLs must not embed credentials')


def dashboard(
    source: dict[str, Any], *, title: str, datasource_variable: str, datasource_uid: str, preset: str, prefix: str = ''
) -> dict[str, Any]:
    result = deepcopy(source)
    result.pop('id', None)
    result.pop('uid', None)  # Imported as a new dashboard; never overwrite an existing UID.
    result['title'] = title
    variables = {row['name']: row for row in result.get('templating', {}).get('list', [])}
    for name, value in [(datasource_variable, datasource_uid), ('preset', preset)]:
        if name not in variables:
            raise ValueError(f'Dashboard lacks required variable: {name}')
        variables[name]['current'] = {'text': value, 'value': value}
    if 'vmanomaly_prefix' in variables:
        variables['vmanomaly_prefix']['query'] = prefix
        variables['vmanomaly_prefix']['current'] = {'text': prefix, 'value': prefix}
    return result


def render(
    artifacts: dict[str, Any], spec: dict[str, Any], anomaly: dict[str, Any], monitoring: dict[str, Any]
) -> dict[str, str]:
    """Render in memory first, so invalid inputs cannot leave a partial bundle."""
    if artifacts.get('schema_version') != 1 or artifacts.get('validation') != 'schema-valid':
        raise ValueError('Expected schema-valid artifact API v1 response')
    config = artifacts['config']
    rules = artifacts['alert_rules']
    for value in (artifacts, spec, anomaly, monitoring):
        check_credentials(value)
    name = spec['name']
    if not isinstance(name, str) or not re.fullmatch(r'[a-z][a-z0-9-]{0,61}[a-z0-9]|[a-z]', name):
        raise ValueError('name must be a DNS label')
    for section in ('reader', 'writer'):
        settings = config.get(section)
        url = settings.get('datasource_url') if isinstance(settings, dict) else None
        if not isinstance(url, str) or not url.strip():
            raise ValueError(f'Deployment rendering requires an explicit {section} datasource URL')
    target = spec['deployment']
    require_pin(spec['vmanomaly_image'])
    fmt = config['writer'].get('metric_format', {'__name__': '$VAR', 'for': '$QUERY_KEY'})
    metric_pattern = fmt['__name__']
    if not metric_pattern.endswith('$VAR') or fmt.get('for') != '$QUERY_KEY':
        raise ValueError('Dashboard adaptation supports metric prefixes and canonical query identity only')
    prefix = metric_pattern[:-4]
    files = {'vmanomaly.yaml': encode(config), 'alerts.yaml': encode(rules)}
    files['anomaly-dashboard.json'] = encode(
        dashboard(
            anomaly,
            title=f'{name}: anomalies',
            datasource_variable='DS_VM',
            datasource_uid=spec['anomaly_datasource_uid'],
            preset=config.get('preset', 'default'),
            prefix=prefix,
        )
    )
    files['self-monitoring-dashboard.json'] = encode(
        dashboard(
            monitoring,
            title=f'{name}: service health',
            datasource_variable='DS_PROMETHEUS',
            datasource_uid=spec['monitoring_datasource_uid'],
            preset=config.get('preset', 'default'),
        )
    )
    pending = [
        'Query/history evidence',
        'Sizing assumptions',
        'Deployment rendering',
        'Live startup',
        'Alert delivery and persistence',
        'Incident navigation',
        'Dashboard query and browser checks',
        'Credential/TLS mounts and durable model/data storage',
    ]
    if target == 'compose':
        require_pin(spec['vmalert_image'])
        files['compose.yaml'] = encode(
            {
                'services': {
                    'vmanomaly': {
                        'image': spec['vmanomaly_image'],
                        'command': ['/config/vmanomaly.yaml'],
                        'environment': {'VM_LICENSE_FILE': '/license'},
                        'volumes': [
                            './vmanomaly.yaml:/config/vmanomaly.yaml:ro',
                            '${VMANOMALY_LICENSE_FILE:?set license path}:/license:ro',
                        ],
                    },
                    'vmalert': {
                        'image': spec['vmalert_image'],
                        'command': [
                            '-rule=/rules/alerts.yaml',
                            '-datasource.url=' + spec['score_datasource_url'],
                            '-notifier.url=' + spec['notifier_url'],
                        ],
                        'volumes': ['./alerts.yaml:/rules/alerts.yaml:ro'],
                    },
                }
            }
        )
    elif target == 'helm':
        if not spec.get('chart_version'):
            raise ValueError('chart_version is required')
        repository, separator, tag = spec['vmanomaly_image'].rpartition(':')
        if not separator or '@' in repository:
            raise ValueError('Helm renderer requires an explicit image tag')
        files['values.yaml'] = encode(
            {
                'config': config,
                'image': {'repository': repository, 'tag': tag},
                'license': {
                    'secret': {'name': spec['license_secret'], 'key': spec.get('license_secret_key', 'license')}
                },
                'resources': spec.get('resources', {}),
            }
        )
        pending.append('Install alerts into the chosen vmalert deployment and import dashboards')
    elif target == 'operator':
        if not spec.get('operator_version'):
            raise ValueError('operator_version is required')
        metadata = {'name': name, 'namespace': spec['namespace']}
        reader, writer = config['reader'], config['writer']
        repository, separator, tag = spec['vmanomaly_image'].rpartition(':')
        if not separator or '@' in repository:
            raise ValueError('Operator renderer requires an explicit image tag')
        files['vmanomaly-resource.yaml'] = encode(
            {
                'apiVersion': 'operator.victoriametrics.com/v1',
                'kind': 'VMAnomaly',
                'metadata': metadata,
                'spec': {
                    'image': {'repository': repository, 'tag': tag},
                    'replicaCount': 1,
                    'reader': {
                        'datasourceURL': reader['datasource_url'],
                        'samplingPeriod': reader.get('sampling_period', '5m'),
                        **({'tenantID': reader['tenant_id']} if reader.get('tenant_id') else {}),
                    },
                    'writer': {
                        'datasourceURL': writer['datasource_url'],
                        **({'tenantID': writer['tenant_id']} if writer.get('tenant_id') else {}),
                    },
                    'configRawYaml': files['vmanomaly.yaml'],
                    'license': {
                        'keyRef': {'name': spec['license_secret'], 'key': spec.get('license_secret_key', 'license')}
                    },
                    'resources': spec.get('resources', {}),
                },
            }
        )
        files['vmrule.yaml'] = encode(
            {
                'apiVersion': 'operator.victoriametrics.com/v1beta1',
                'kind': 'VMRule',
                'metadata': {**metadata, 'labels': spec['rule_labels']},
                'spec': rules,
            }
        )
        pending.append('Verify VMAlert selects the VMRule and test config precedence after reconciliation')
    else:
        raise ValueError('deployment must be compose, helm or operator')
    manifest = {
        'schema_version': 1,
        'name': name,
        'deployment': target,
        'backend_validation': artifacts['validation'],
        'warnings': artifacts.get('warnings', []),
        'deployment_spec': spec,
        'pending_validation': pending,
        'files': {key: sha256(value.encode()) for key, value in files.items()},
    }
    files['manifest.json'] = encode(manifest)
    return files


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ['artifacts', 'spec', 'anomaly-dashboard', 'monitoring-dashboard', 'output']:
        parser.add_argument('--' + name, type=Path, required=True)
    args = parser.parse_args()
    artifacts, spec = load_json(args.artifacts), load_json(args.spec)
    # Parse the same bytes whose checksum was verified, even if a file changes concurrently.
    anomaly = load_json(args.anomaly_dashboard, spec['dashboard_sha256']['anomaly'])
    monitoring = load_json(args.monitoring_dashboard, spec['dashboard_sha256']['monitoring'])
    files = render(artifacts, spec, anomaly, monitoring)
    args.output.mkdir(parents=False, exist_ok=False)
    for name, content in files.items():
        (args.output / name).write_text(content, encoding='utf-8')


if __name__ == '__main__':
    main()
