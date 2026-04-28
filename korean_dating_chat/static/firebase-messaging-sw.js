// Firebase Messaging Service Worker
// 루트 경로(/firebase-messaging-sw.js)에서 제공됨 (chatbot.py 라우트)

importScripts('https://www.gstatic.com/firebasejs/10.8.0/firebase-app-compat.js');
importScripts('https://www.gstatic.com/firebasejs/10.8.0/firebase-messaging-compat.js');

firebase.initializeApp({
    apiKey: "AIzaSyClrG63hvRhUoI_EVl79xFFV9VCXCx673k",
    authDomain: "my-k-dating-app.firebaseapp.com",
    projectId: "my-k-dating-app",
    storageBucket: "my-k-dating-app.firebasestorage.app",
    messagingSenderId: "515513943326",
    appId: "1:515513943326:web:ea256f3a704d914ff1f50f"
});

const messaging = firebase.messaging();

// 백그라운드 메시지 처리 (앱이 닫혀 있을 때)
messaging.onBackgroundMessage((payload) => {
    console.log('[SW] Background message:', payload);

    const title = payload.notification?.title || 'K-Dating Chat';
    const options = {
        body: payload.notification?.body || '',
        icon: payload.notification?.icon || '/static/jiwoo_profile.png',
        tag: payload.data?.tag || 'kdating',
        renotify: true,
        data: { url: payload.fcmOptions?.link || '/' }
    };

    return self.registration.showNotification(title, options);
});

// 알림 클릭 처리
self.addEventListener('notificationclick', (event) => {
    event.notification.close();
    const urlToOpen = event.notification.data?.url || '/';

    event.waitUntil(
        clients.matchAll({ type: 'window', includeUncontrolled: true })
            .then((windowClients) => {
                for (const client of windowClients) {
                    if (client.url.includes(self.location.origin) && 'focus' in client) {
                        client.postMessage({
                            type: 'NOTIFICATION_CLICK',
                            url: urlToOpen
                        });
                        return client.focus();
                    }
                }
                return clients.openWindow(urlToOpen);
            })
    );
});
