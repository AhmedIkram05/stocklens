# StockLens 📱

> Scan Your Spending. See Your Missed Investing.

A full-stack mobile app that helps users understand how their daily spending habits translate into missed investment opportunities. Built with React Native and Expo, StockLens uses OCR to scan physical receipts, structures the data, and shows users what that money could have grown to if invested instead.

## 📸 Screenshots

| Welcome | Dashboard | Receipt Details |
|---|---|---|
| <img src="assets/screenshots/splash.png" width="200"/> | <img src="assets/screenshots/home2.png" width="200"/> | <img src="assets/screenshots/receiptDetails.png" width="200"/> |

## 🧠 Tech Stack

- **React Native (Expo)** — Cross-platform mobile app (iOS & Android)
- **TypeScript** — Strongly typed throughout for reliability and maintainability
- **Firebase** — Authentication (email/password) and Firestore real-time database
- **OCR** — Receipt scanning and text extraction pipeline
- **Expo Camera / Image Picker** — Camera integration for receipt capture

## ✨ Features

- **Receipt Scanning** — Point your camera at any receipt; the OCR pipeline extracts, parses, and structures the data automatically
- **Investment Projections** — See what your spending could have grown to if invested in stocks or index funds over time
- **Dashboard** — Visual overview of spending trends and missed investment potential
- **Secure Auth** — Firebase email/password authentication with persistent sessions
- **Real-time Sync** — All receipt and financial data syncs across devices via Firestore
- **Clean Architecture** — Strict separation between data, business logic, and UI layers throughout the TypeScript codebase

## 📁 Project Structure

```
stocklens/
├── src/
│   ├── __tests__/          # Unit and integration test suites
│   │   ├── fixtures/       # Mock data (receipts, users, OCR responses)
│   │   ├── hooks/          # Custom hook tests
│   │   ├── screens/        # Screen and workflow tests
│   │   └── services/       # OCR, projections, and database logic tests
│   ├── components/         # Reusable UI components
│   ├── screens/            # App screens
│   ├── services/           # OCR processing, investment logic, Firebase
│   ├── hooks/              # Custom React hooks
│   └── utils/              # Formatters and helpers
├── assets/
│   └── screenshots/        # App screenshots
├── app.json                # Expo configuration
└── package.json
```

## 🧪 How to Run

### Prerequisites
- Node.js (LTS, e.g. Node 18+)
- npm or Yarn
- Android/iOS emulator or the Expo Go app on your phone

### Steps

```bash
git clone https://github.com/AhmedIkram05/StockLens.git
cd StockLens
npm install
npm update
npm start
```

Then:
- Press `i` for iOS simulator
- Press `a` for Android emulator
- Scan the QR code with Expo Go for a physical device

### Running Tests

```bash
npm test              # Full test suite
npm test unit         # Unit tests only
npm test integration  # Integration tests only
```
