/* Firebase Messaging service worker — project taxitips-se */
/* eslint-disable no-undef */
importScripts('https://www.gstatic.com/firebasejs/10.14.0/firebase-app-compat.js');
importScripts('https://www.gstatic.com/firebasejs/10.14.0/firebase-messaging-compat.js');

firebase.initializeApp({
  apiKey: 'AIzaSyC8EoR1vv95zfhlnMwIDsnfMikUPh4d1pU',
  authDomain: 'taxitips-se.firebaseapp.com',
  projectId: 'taxitips-se',
  storageBucket: 'taxitips-se.firebasestorage.app',
  messagingSenderId: '1015418824161',
  appId: '1:1015418824161:web:a8462870b4b2801e859ea0',
});

firebase.messaging();
