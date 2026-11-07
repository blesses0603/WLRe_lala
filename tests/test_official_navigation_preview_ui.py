import os
import unittest
from unittest.mock import Mock,patch


@unittest.skipUnless(os.environ.get('DISPLAY'),'display required')
class OfficialPreviewUITests(unittest.TestCase):
    def test_read_only_actions_render_and_validation_persists(self):
        import tkinter as tk
        from wlre.ui.official_navigation_preview import OfficialNavigationPreview
        root=tk.Tk();root.withdraw();job=Mock()
        job.poll.return_value={'status':'ready','message':'preview only','result':dict(logical_map=10000,catalog_key='a'*64,packet_points_xy_float=[[1,2],[3,4]])}
        with patch('wlre.ui.official_navigation_preview.PreviewJob',return_value=job):
            view=OfficialNavigationPreview(root,lambda:{'player':{'scene':10000,'x':1,'y':2}})
            try:
                view.run(False);self.assertFalse(job.start.call_args.kwargs['download'])
                view.window.after_cancel(view.timer);view.poll()
                self.assertIn('1.00, 2.00',view.output.get('1.0','end'))
                job.start.side_effect=ValueError('invalid input');view.run(True)
                view.window.after_cancel(view.timer);view.poll()
                self.assertEqual(view.status.get(),'invalid input')
                self.assertEqual(view.output.get('1.0','end').strip(),'')
            finally:view.close();root.destroy()
        job.close.assert_called()


if __name__=='__main__':unittest.main()
