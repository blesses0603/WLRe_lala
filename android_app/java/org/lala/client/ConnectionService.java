package org.lala.client;

import android.app.*;
import android.content.*;
import android.os.*;
import org.kivy.android.PythonActivity;
import org.kivy.android.PythonService;

/** Foreground notification owns stop action; Android 15 timeout stops safely. */
public class ConnectionService extends PythonService {
    @Override public int onStartCommand(Intent intent, int flags, int startId) {
        if (intent != null && "WLRE_STOP".equals(intent.getAction())) {
            stopSelf();
            return START_NOT_STICKY;
        }
        return super.onStartCommand(intent, flags, startId);
    }
    @Override protected void doStartForeground(Bundle extras) {
        String channel = "wlre_connections";
        NotificationManager manager = (NotificationManager)getSystemService(NOTIFICATION_SERVICE);
        if (Build.VERSION.SDK_INT >= 26)
            manager.createNotificationChannel(new NotificationChannel(channel,
                "帳號連線", NotificationManager.IMPORTANCE_LOW));
        Intent open = new Intent(this, PythonActivity.class);
        Intent stop = new Intent(this, getClass()).setAction("WLRE_STOP");
        int immutable = PendingIntent.FLAG_IMMUTABLE | PendingIntent.FLAG_UPDATE_CURRENT;
        Notification.Builder builder = Build.VERSION.SDK_INT >= 26
            ? new Notification.Builder(this, channel) : new Notification.Builder(this);
        builder.setSmallIcon(getApplicationInfo().icon).setContentTitle("WLRe_LaLa")
            .setContentText("帳號連線服務運作中；點擊返回")
            .setContentIntent(PendingIntent.getActivity(this, 0, open, immutable))
            .setOngoing(true).setVisibility(Notification.VISIBILITY_PRIVATE)
            .addAction(new Notification.Action.Builder(null, "停止全部連線",
                PendingIntent.getService(this, 1, stop, immutable)).build());
        startForeground(getServiceId(), builder.build());
    }
    @Override public void onTimeout(int startId, int foregroundServiceType) {
        stopSelf();
    }
}
