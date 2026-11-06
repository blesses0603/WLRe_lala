from types import SimpleNamespace
import threading
import unittest
from unittest.mock import Mock
from wlre.services.world.navigation_preview_job import PreviewJob
from wlre.services.world.movement import Movement
from wlre.network.wire import ProtocolError
from wlre.core.state import State


def runtime():return SimpleNamespace(catalog_identity=SimpleNamespace(key='a'*64),stages={})
def state():return dict(player=dict(role_id=1,scene=10000),navigation=dict(scene=10000,revision=1,stale=False))
def result():return dict(can_send_packets=False,points=[(1,2,3)],cost=10)


class PreviewJobTests(unittest.TestCase):
    def test_cold_start_and_bad_coordinates(self):
        with self.assertRaises(ValueError):PreviewJob(runtime_getter=lambda:None).start(state(),10000,(0,0),(1,1))
        r=runtime();job=PreviewJob(runtime_getter=lambda:r)
        with self.assertRaises(ValueError):job.start(state(),10000,(0,0),(float('nan'),1))

    def test_versions_and_obstacles_invalidate_results(self):
        r=runtime();source=[r];repo=Mock();repo.route.return_value=result()
        job=PreviewJob(repository_factory=lambda *_:repo,runtime_getter=lambda:source[0]);s=state()
        job.start(s,10000,(0,0),(1,1),download=False);job.worker.join(2)
        self.assertEqual(job.poll(s)['status'],'ready')
        s['navigation']['revision']=2;self.assertEqual(job.poll(s)['status'],'stale')
        s['navigation']['revision']=1;source[0]=runtime();self.assertEqual(job.poll(s)['status'],'stale')
        self.assertNotIn('result',job.poll(s))

    def test_one_worker_and_closed_window_drop_result(self):
        r=runtime();release=threading.Event();repo=Mock()
        repo.route.side_effect=lambda *a,**kw:(release.wait(2),result())[1]
        job=PreviewJob(repository_factory=lambda *_:repo,runtime_getter=lambda:r);s=state()
        job.start(s,10000,(0,0),(1,1))
        try:
            with self.assertRaises(ValueError):job.start(s,10000,(0,0),(1,1))
            job.close()
        finally:release.set();job.worker.join(2)
        self.assertEqual(job.poll(s)['status'],'closed')

    def test_movement_rejects_preview_result_before_activation(self):
        s=State();s.player=dict(role_id=1,scene=10000,x=100,y=100)
        s.confirm_location(10000,100,100,'S3-1')
        converter=Mock();converter.route.return_value=result()
        movement=Movement(converter,Mock())
        with self.assertRaisesRegex(ProtocolError,'僅供預覽'):movement.start(s,200,200,0)
        self.assertFalse(movement.active)


if __name__=='__main__':unittest.main()
