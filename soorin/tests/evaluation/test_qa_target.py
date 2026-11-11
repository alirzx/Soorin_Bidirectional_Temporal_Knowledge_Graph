import unittest
from soorin.e2e.qa_target import PROJECT, verify_qa_target
from soorin.e2e.local_validation import select_isolated_api


def container(service):
    app = service == 'app'
    return {'Config': {'Labels': {'com.docker.compose.project':PROJECT, 'com.docker.compose.service':service}},
            'State': {'Running':True},
            'Mounts':[{'Destination':'/app/data' if app else '/var/lib/postgresql/data', 'Type':'volume',
                       'Name':PROJECT + '_soorin_sprint1_' + ('data' if app else 'db')}],
            'NetworkSettings':{'Ports':{('1516/tcp' if app else '5432/tcp'):[{'HostIp':'127.0.0.1','HostPort':'2526' if app else '2527'}]}}}


class QaTargetTests(unittest.TestCase):
    def test_explicit_project_and_port_do_not_bypass_old_lab_gate(self):
        url = 'http://127.0.0.1:2526'
        self.assertEqual(select_isolated_api(url, qa_project=PROJECT, approved_port=2526), url)
        verify_qa_target(url, PROJECT, inspect=container)
        for port in [1516,2516,2517,2527]:
            with self.assertRaises(ValueError):
                select_isolated_api(f'http://127.0.0.1:{port}', qa_project=PROJECT, approved_port=2526)
        with self.assertRaises(ValueError):
            verify_qa_target('http://127.0.0.1:2516', PROJECT, inspect=container)

    def test_wrong_stack_reused_volume_and_public_port_fail_closed(self):
        for defect in ['project','volume','bind']:
            def inspect(service):
                row=container(service)
                if defect == 'project': row['Config']['Labels']['com.docker.compose.project']='old-lab'
                if defect == 'volume': row['Mounts'][0]['Name']='soorin-sprint1_db'
                if defect == 'bind':
                    for binding in row['NetworkSettings']['Ports'].values(): binding[0]['HostIp']='0.0.0.0'
                return row
            with self.subTest(defect=defect), self.assertRaises(ValueError):
                verify_qa_target('http://127.0.0.1:2526', PROJECT, inspect=inspect)
