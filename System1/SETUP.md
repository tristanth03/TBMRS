# Nitrate — Setup Guide

A personal movie tracker powered by IMDb API + Firebase.

## 1. Create a Firebase Project

1. Go to [console.firebase.google.com](https://console.firebase.google.com)
2. Click **"Create a project"** (or "Add project")
3. Name it whatever you like (e.g. `nitrate-movies`)
4. Disable Google Analytics (not needed) → **Create Project**

## 2. Add a Web App

1. In the project dashboard, click the **web icon** (`</>`)
2. Give it a nickname (e.g. `nitrate-web`)
3. ✅ Check **"Also set up Firebase Hosting"** if you want Firebase hosting (optional — GitHub Pages works too)
4. Click **Register app**
5. You'll see a config block like this — **copy it**:

```javascript
const firebaseConfig = {
  apiKey: "AIza...",
  authDomain: "your-project.firebaseapp.com",
  projectId: "your-project",
  storageBucket: "your-project.appspot.com",
  messagingSenderId: "123456789",
  appId: "1:123456789:web:abc123"
};
```

6. Paste these values into `index.html` where it says `// 🔥 PASTE YOUR FIREBASE CONFIG HERE`

## 3. Enable Google Sign-In

1. In the Firebase console, go to **Build → Authentication**
2. Click **"Get started"**
3. Go to the **Sign-in method** tab
4. Click **Google** → **Enable** it
5. Pick a support email → **Save**

## 4. Create Firestore Database

1. Go to **Build → Firestore Database**
2. Click **"Create database"**
3. Choose **"Start in test mode"** (we'll lock it down next)
4. Pick a region close to you → **Enable**

## 5. Set Security Rules

1. In Firestore, go to the **Rules** tab
2. Replace the default rules with:

```
rules_version = '2';
service cloud.firestore {
  match /databases/{database}/documents {
    // Users can only read/write their own data
    match /users/{userId}/{document=**} {
      allow read, write: if request.auth != null && request.auth.uid == userId;
    }
  }
}
```

3. Click **Publish**

This ensures each user can only access their own movie data.

## 6. Add Your Domain to Authorized Domains

1. Go to **Build → Authentication → Settings**
2. Under **Authorized domains**, add:
   - `yourusername.github.io` (for GitHub Pages)
   - `localhost` (for local testing)

## 7. Deploy to GitHub Pages

1. Create a new GitHub repository (e.g. `nitrate`)
2. Upload `index.html` to the repo
3. Go to **Settings → Pages**
4. Under **Source**, select **"Deploy from a branch"**
5. Choose **main** branch, **/ (root)** folder → **Save**
6. Your site will be live at `https://yourusername.github.io/nitrate/`

## 8. Local Testing

To test locally before deploying:

```bash
# Simple Python server
python -m http.server 8000

# Then open http://localhost:8000
```

## Troubleshooting

**"popup closed by user"** → Make sure your domain is in Firebase Authorized Domains.

**CORS errors on IMDB API** → The app includes a fallback CORS proxy. If that fails too, check the browser console for details.

**"permission denied" on Firestore** → Double-check the security rules match step 5 exactly, and that you're signed in.

**Movies not loading** → The IMDB API (imdbapi.dev) is free but rate-limited. Wait a moment and try again.
