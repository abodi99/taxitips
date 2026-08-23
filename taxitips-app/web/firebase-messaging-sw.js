/* Firebase Messaging service worker — project taxibehov */
/* eslint-disable no-undef */
importScripts('https://www.gstatic.com/firebasejs/10.14.0/firebase-app-compat.js');
importScripts('https://www.gstatic.com/firebasejs/10.14.0/firebase-messaging-compat.js');

firebase.initializeApp({
  apiKey: 'AIzaSyDoKaLhJptAWUpbw2vh1pJ61YRb7kau2zU',
  authDomain: 'taxibehov.firebaseapp.com',
  projectId: 'taxibehov',
  storageBucket: 'taxibehov.firebasestorage.app',
  messagingSenderId: '963263574599',
  appId: '1:963263574599:web:f8fffff4809589607f7762',
});

firebase.messaging();
