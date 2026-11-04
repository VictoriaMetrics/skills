"""Deterministic artifact assembly tests; these do not claim live deployment validation."""

import hashlib
import importlib.util
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

SCRIPT = Path(__file__).parents[1] / 'skills/vmanomaly-preset/scripts/render_bundle.py'
spec = importlib.util.spec_from_file_location('render_bundle', SCRIPT)
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


class BundleTests(unittest.TestCase):
    def setUp(self):
        self.artifacts = {
            'schema_version': 1,
            'validation': 'schema-valid',
            'warnings': ['fixture'],
            'config': {
                'reader': {'datasource_url': 'https://read.example'},
                'writer': {'datasource_url': 'https://write.example'},
                'models': {'a': {'queries': ['q1', 'q2']}},
            },
            'alert_rules': {'groups': []},
        }
        self.artifacts['config_yaml'] = json.dumps(self.artifacts['config'])
        self.artifacts['alerts_yaml'] = json.dumps(self.artifacts['alert_rules'])
        self.spec = {
            'name': 'demo',
            'deployment': 'compose',
            'vmanomaly_image': 'victoriametrics/vmanomaly:v1.31.0',
            'vmalert_image': 'victoriametrics/vmalert:v1.126.0',
            'score_datasource_url': 'https://scores.example',
            'notifier_url': 'https://notify.example',
            'anomaly_datasource_uid': 'scores',
            'monitoring_datasource_uid': 'monitoring',
        }
        self.anomaly = {
            'id': 1,
            'uid': 'existing',
            'panels': [{'targets': [{'expr': 'keep{for="q1|q2"}'}]}],
            'templating': {'list': [{'name': 'DS_VM'}, {'name': 'preset'}, {'name': 'vmanomaly_prefix'}]},
        }
        self.monitoring = {'templating': {'list': [{'name': 'DS_PROMETHEUS'}, {'name': 'preset'}]}}

    def test_preserves_complete_artifact_text_and_draft_metadata(self):
        self.artifacts['config_yaml'] = '# DRAFT: replace writer URL\n' + self.artifacts['config_yaml']
        self.artifacts['alerts_yaml'] = '# DRAFT: verify score destination\n' + self.artifacts['alerts_yaml']
        self.artifacts['required_inputs'] = [{'field': 'writer.datasource_url', 'instruction': 'Replace URL'}]
        files = module.render(self.artifacts, self.spec, self.anomaly, self.monitoring)
        self.assertEqual(files['vmanomaly.yaml'], self.artifacts['config_yaml'])
        self.assertEqual(files['alerts.yaml'], self.artifacts['alerts_yaml'])
        manifest = json.loads(files['manifest.json'])
        self.assertFalse(manifest['deployment_ready'])
        self.assertEqual(manifest['required_inputs'], self.artifacts['required_inputs'])

    def test_yaml12_scalars_preserve_artifact_text(self):
        labels = {'on': 'off', 'yes': 'no', 'date': '2026-10-28', 'time': '12:34:56'}
        self.artifacts['alert_rules'] = {'groups': [], 'labels': labels, 'enabled': True, 'count': 12, 'ratio': 1000.0}
        content = ('# Keep this comment\ngroups: []\nlabels: {on: off, yes: no, date: 2026-10-28, time: 12:34:56}\n'
                   'enabled: true\ncount: 012\nratio: 1e3\n')
        self.artifacts['alerts_yaml'] = content
        files = module.render(self.artifacts, self.spec, self.anomaly, self.monitoring)
        self.assertEqual(files['alerts.yaml'], content)

    def test_yaml12_string_bool_mismatch_is_rejected(self):
        self.artifacts['alert_rules'] = {'groups': [], 'label': True}
        self.artifacts['alerts_yaml'] = 'groups: []\nlabel: on\n'
        with self.assertRaisesRegex(ValueError, 'differs from its structured object'):
            module.render(self.artifacts, self.spec, self.anomaly, self.monitoring)

    def test_duplicate_yaml_keys_are_rejected(self):
        self.artifacts['alerts_yaml'] = 'groups: []\ngroups: []\n'
        with self.assertRaisesRegex(ValueError, 'Invalid artifact YAML'):
            module.render(self.artifacts, self.spec, self.anomaly, self.monitoring)

    def test_rejects_spliced_artifact_yaml(self):
        for field in ('config_yaml', 'alerts_yaml'):
            with self.subTest(field=field):
                original = self.artifacts[field]
                self.artifacts[field] = 'different: content\n'
                with self.assertRaisesRegex(ValueError, 'differs from its structured object'):
                    self.render()
                self.artifacts[field] = original

    def test_rejects_unsafe_yaml_tags(self):
        self.artifacts['config_yaml'] = '!!python/object/apply:os.system [echo unsafe]'
        with self.assertRaisesRegex(ValueError, 'Invalid artifact YAML'):
            self.render()

    def test_rejects_incomplete_artifact_pair(self):
        del self.artifacts['alerts_yaml']
        with self.assertRaisesRegex(ValueError, 'regenerate the artifact pair'):
            module.render(self.artifacts, self.spec, self.anomaly, self.monitoring)

    def render(self):
        return module.render(self.artifacts, self.spec, self.anomaly, self.monitoring)

    def test_preserves_queries_and_distinct_datasources(self):
        files = self.render()
        config = json.loads(files['vmanomaly.yaml'])
        self.assertEqual(config, self.artifacts['config'])
        dash = json.loads(files['anomaly-dashboard.json'])
        self.assertEqual(dash['panels'], self.anomaly['panels'])
        self.assertNotIn('uid', dash)
        compose = json.loads(files['compose.yaml'])
        self.assertIn('-datasource.url=https://scores.example', compose['services']['vmalert']['command'])
        self.assertEqual(compose['services']['vmanomaly']['command'], ['/config/vmanomaly.yaml'])
        manifest = json.loads(files['manifest.json'])
        self.assertIn('Live startup', manifest['pending_validation'])
        self.assertEqual(manifest['warnings'], ['fixture'])
        self.assertEqual(files, self.render())

    def test_kubernetes_modes(self):
        for mode in ['helm', 'operator']:
            with self.subTest(mode=mode):
                self.spec.update(
                    deployment=mode,
                    chart_version='1.0.0',
                    operator_version='0.1.0',
                    namespace='monitoring',
                    license_secret='existing-license',
                    rule_labels={'team': 'observability'},
                )
                files = self.render()
                if mode == 'helm':
                    self.assertEqual(json.loads(files['values.yaml'])['config'], self.artifacts['config'])
                else:
                    cr = json.loads(files['vmanomaly-resource.yaml'])
                    self.assertEqual(json.loads(cr['spec']['configRawYaml']), self.artifacts['config'])
                    self.assertNotIn('configSecret', cr['spec'])
                    self.assertEqual(cr['spec']['replicaCount'], 1)

    def test_rejects_mutable_image_and_inline_credentials(self):
        self.spec['vmanomaly_image'] = 'victoriametrics/vmanomaly:latest'
        with self.assertRaises(ValueError):
            self.render()
        self.spec['vmanomaly_image'] = 'victoriametrics/vmanomaly:v1.31.0'
        self.artifacts['config']['reader']['password'] = 'do-not-export'
        with self.assertRaises(ValueError):
            self.render()

    def test_requires_reader_and_writer_destinations_for_every_target(self):
        for target in ('compose', 'helm', 'operator'):
            for section in ('reader', 'writer'):
                for settings in (None, {}, {'datasource_url': ''}, {'datasource_url': '  '}, {'datasource_url': 1}):
                    with self.subTest(target=target, section=section, settings=settings):
                        self.setUp()
                        self.spec['deployment'] = target
                        self.artifacts['config'][section] = settings
                        with self.assertRaisesRegex(ValueError, f'explicit {section} datasource URL'):
                            self.render()

    def test_bundle_name_boundaries(self):
        for name in ('0', '2024-prod', 'a', 'a' * 63):
            with self.subTest(name=name):
                self.spec['name'] = name
                self.assertEqual(json.loads(self.render()['manifest.json'])['name'], name)
        for name in ('', '-demo', 'demo-', 'Demo', 'a' * 64, 'demo.example', 'demo_1'):
            with self.subTest(name=name), self.assertRaisesRegex(ValueError, 'DNS label'):
                self.spec['name'] = name
                self.render()

    def test_rejects_padded_urls_without_mutating_inputs(self):
        for target in ('compose', 'helm', 'operator'):
            for section in ('reader', 'writer'):
                for url in (' https://example.com', 'https://example.com\n', '\thttps://example.com '):
                    with self.subTest(target=target, section=section, url=url):
                        self.setUp()
                        self.spec['deployment'] = target
                        self.artifacts['config'][section]['datasource_url'] = url
                        before = json.dumps(self.artifacts)
                        with self.assertRaisesRegex(ValueError, 'surrounding whitespace'):
                            self.render()
                        self.assertEqual(json.dumps(self.artifacts), before)

    def test_compose_requires_unpadded_alert_destinations(self):
        for field in ('score_datasource_url', 'notifier_url'):
            for value in (None, '', ' ', 1, ' https://example.com', 'https://example.com\n'):
                with self.subTest(field=field, value=value):
                    self.setUp()
                    self.spec[field] = value
                    with self.assertRaisesRegex(ValueError, field):
                        self.render()

    def test_checks_credentials_in_all_exported_inputs(self):
        for field in ('api_key', 'access_token', 'password'):
            for source in ('config', 'alert_rules', 'warnings', 'spec', 'anomaly', 'monitoring'):
                with self.subTest(field=field, source=source):
                    self.setUp()
                    value = {'nested': [{field: 'do-not-export'}]}
                    if source == 'warnings':
                        self.artifacts['warnings'] = [value]
                    else:
                        target = (
                            self.artifacts[source] if source in ('config', 'alert_rules') else getattr(self, source)
                        )
                        target['extra'] = value
                    with self.assertRaisesRegex(ValueError, 'inline credentials'):
                        self.render()
        self.setUp()
        self.spec['credentials'] = {'api_key_file': '/secrets/key', 'access_token_file': '/secrets/token'}
        self.render()

    def test_image_reference_syntax(self):
        for image in ('repo:latest ', 'repo:v1 bad', 'repo:', 'repo', 'repo:tag/path', 'repo@sha256:bad'):
            with self.subTest(image=image), self.assertRaises(ValueError):
                module.require_pin(image)
        for image in ('repo:v', 'repo:build-abc', 'registry:5000/repo:v1.2.3', 'repo@sha256:' + 'a' * 64):
            with self.subTest(image=image):
                module.require_pin(image)

    def test_rejects_unsupported_dashboard_format(self):
        self.artifacts['config']['writer']['metric_format'] = {'__name__': '$VAR_suffix', 'for': '$QUERY_KEY'}
        with self.assertRaises(ValueError):
            self.render()

    def test_cli_verifies_checksums_and_never_overwrites(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            paths = {}
            for name, value in [
                ('artifacts', self.artifacts),
                ('anomaly-dashboard', self.anomaly),
                ('monitoring-dashboard', self.monitoring),
            ]:
                paths[name] = root / (name + '.json')
                paths[name].write_text(json.dumps(value), encoding='utf-8')
            self.spec['dashboard_sha256'] = {
                label: hashlib.sha256(paths[name].read_bytes()).hexdigest()
                for label, name in [('anomaly', 'anomaly-dashboard'), ('monitoring', 'monitoring-dashboard')]
            }
            paths['spec'] = root / 'spec.json'
            paths['spec'].write_text(json.dumps(self.spec), encoding='utf-8')
            paths['output'] = root / 'bundle'
            command = [sys.executable, str(SCRIPT)]
            for name, path in paths.items():
                command.extend(['--' + name, str(path)])
            result = subprocess.run(command, capture_output=True, timeout=10)
            self.assertEqual(result.returncode, 0, result.stderr)
            manifest = (paths['output'] / 'manifest.json').read_bytes()
            self.assertNotEqual(subprocess.run(command, capture_output=True, timeout=10).returncode, 0)
            self.assertEqual((paths['output'] / 'manifest.json').read_bytes(), manifest)
            tampered = {**self.anomaly, 'title': 'A different valid title'}
            paths['anomaly-dashboard'].write_text(json.dumps(tampered), encoding='utf-8')
            command[-1] = str(root / 'mismatch')
            result = subprocess.run(command, capture_output=True, timeout=10)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn(b'Checksum mismatch', result.stderr)
            self.assertFalse((root / 'mismatch').exists())


if __name__ == '__main__':
    unittest.main()
