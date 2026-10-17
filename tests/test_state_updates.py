import unittest
from unittest.mock import Mock,patch
from wlre.network.state_updates import StatePublisher,notify_state
from wlre.network.client import run_client


class DisplayUpdates(unittest.TestCase):
    def test_burst_copies_only_when_due_and_flushes_latest(self):
        clock=Mock(return_value=0)
        state=Mock();state.snapshot.side_effect=lambda:{'value':state.value}
        values=[];publisher=StatePublisher(values.append,0.1,clock)
        for number in range(1000):
            state.value=number;publisher.publish(state)
        self.assertEqual(state.snapshot.call_count,1)
        self.assertEqual(values,[{'value':0}])
        clock.return_value=0.1;publisher.flush(state)
        self.assertEqual(values[-1],{'value':999})
        publisher.flush(state)
        self.assertEqual(state.snapshot.call_count,2)

    def test_disconnect_forces_final_state_within_interval(self):
        state=Mock();state.snapshot.return_value={'phase':'world_ready'}
        values=[];publisher=StatePublisher(values.append,1,lambda:0)
        publisher.publish(state)
        state.snapshot.return_value={'phase':'disconnected'}
        notify_state(publisher,state,force=True)
        self.assertEqual(values[-1],{'phase':'disconnected'})

    def test_instances_do_not_share_throttling(self):
        a=Mock();b=Mock();state=Mock()
        first=StatePublisher(a,1,lambda:0);second=StatePublisher(b,1,lambda:0)
        first.publish(state);first.publish(state);second.publish(state)
        self.assertEqual(a.call_count,1)
        self.assertEqual(b.call_count,1)

    def test_plain_callback_remains_immediate(self):
        callback=Mock();state=Mock()
        notify_state(callback,state);notify_state(callback,state)
        self.assertEqual(callback.call_count,2)

    def test_network_burst_preserves_every_event_and_final_state(self):
        connection=Mock()
        connection.recv.side_effect=[b'fixture',b'']
        context=Mock();context.__enter__=Mock(return_value=connection);context.__exit__=Mock(return_value=False)
        decoder=Mock();decoder.feed.return_value=range(100)
        events=[{'type':'team_flag','enabled':bool(i%2)} for i in range(100)]
        states=[];emitted=[]
        with patch('wlre.network.client.socket.create_connection',return_value=context),patch('wlre.network.client.FrameDecoder',return_value=decoder),patch('wlre.network.client.decode',side_effect=events):
            result=run_client('localhost',12345,{'rx_xor':0,'tx_xor':0},emitted.append,on_state=states.append,snapshot_interval=60)
        self.assertEqual(len([e for e in emitted if e['type']=='team_flag']),100)
        self.assertTrue(result.party['enabled'])
        self.assertTrue(states[-1]['party']['enabled'])
        self.assertEqual(len(states),2)
        self.assertEqual(emitted[-1]['type'],'connection_closed')
