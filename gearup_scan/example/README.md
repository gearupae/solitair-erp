# Gearup scan — example app

1. Install Flutter, then from this folder generate platform projects (once):

   ```bash
   flutter create .
   ```

2. Set **base URL** in the app to your ERP origin (no trailing slash), e.g.:

   - Android emulator → host machine: `http://10.0.2.2:7001`
   - iOS simulator: `http://127.0.0.1:7001`
   - Device on LAN: `http://192.168.x.x:7001` (use your machine’s IP; Django `ALLOWED_HOSTS` must include it)

3. Run:

   ```bash
   flutter pub get
   flutter run
   ```

Use the same **username / password** as the web ERP. Inventory **view** is required to list sessions; **edit** is required to submit scans.
