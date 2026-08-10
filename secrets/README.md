# secrets/

Maxfiy fayllar uchun (Firebase service account va h.k.). Bu papkadagi fayllar
git'ga **chiqmaydi** (`.gitignore` — faqat shu README va `.gitkeep` kuzatiladi).

## Firebase push (FCM)

1. Firebase Console → Project Settings → Service accounts → *Generate new private key*.
2. Olingan `.json`ni shu papkaga qo'ying, masalan `secrets/fcm.json`.
3. `.env`da to'liq yo'lini ko'rsating:
   ```
   FCM_SERVICE_ACCOUNT_FILE=/абсолют/йўл/aylanai/secrets/fcm.json
   ```
4. Ruxsatni cheklang:
   ```
   chmod 600 secrets/fcm.json
   ```

> ⚠️ Bu fayllarni HECH QACHON commit qilmang va nginx bilan bermang (static/media emas).