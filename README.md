# 🚀 Docqify AI

**Docqify AI** is a modern web-based platform for creating professional documents like resumes, cover letters, SOPs, and official drafts with ease. It provides a clean UI, ready-to-use templates, AI-assisted writing, and seamless PDF downloads — all in one place.

---

## ✨ Features

* 🧠 **AI-Powered Content Generation** (Gemini/OpenAI support)
* 📄 **Multiple Document Templates**

  * Resume, CV
  * Cover Letter, SOP, LOR
  * HR & Workplace Documents
  * Government & Official Drafts
* ⚡ **Live Preview Editor**
* 📥 **PDF Download Functionality**
* 💳 **Razorpay Payment Integration**
* 🔐 **Admin Dashboard for Configuration**
* 🎨 **Modern UI with Clean UX**

---

## 🛠️ Tech Stack

* **Frontend:** HTML, CSS, JavaScript
* **Backend:** Python (Flask)
* **AI Integration:** Google Gemini API / OpenAI
* **Payment Gateway:** Razorpay
* **Deployment:** Render
* **Version Control:** Git & GitHub

---

## 📁 Project Structure

```
Docqify-production/
│── static/              # CSS, JS, Images
│── templates/           # HTML templates
│── main.py              # Flask backend
│── admin_settings.json  # App configurations
│── requirements.txt     # Dependencies
│── README.md
```

---

## ⚙️ Installation & Setup

### 1️⃣ Clone the repository

```
git clone https://github.com/docqifyai/Docqify-production.git
cd Docqify-production
```

---

### 2️⃣ Create virtual environment

```
python -m venv venv
venv\Scripts\activate   # Windows
```

---

### 3️⃣ Install dependencies

```
pip install -r requirements.txt
```

---

### 4️⃣ Run the project

```
python main.py
```

👉 Open in browser:
`http://127.0.0.1:5000`

---

## 🔐 Environment Variables (Important)

Create a `.env` file (optional but recommended):

```
GOOGLE_API_KEY=your_api_key_here
```

---

## 💳 Razorpay Setup

1. Go to Razorpay Dashboard
2. Generate API Keys
3. Add in Admin Panel:

   * `Razorpay Key ID`
   * `Razorpay Secret`

👉 Use **Test Keys** for local development

---

## 🚀 Deployment (Render)

1. Push project to GitHub
2. Connect GitHub repo to Render
3. Add environment variables
4. Deploy 🚀

---

## 📸 Screenshots

*(Add your project screenshots here for better presentation)*

---

## 👨‍💻 Author

**Docqify**

* GitHub: https://github.com/docqifyai

---

## 📌 Future Improvements

* Better AI suggestions
* Multi-language support
* Document templates expansion
* User authentication system

---

## ⭐ Contribution

Contributions are welcome! Feel free to fork this repo and improve it.

---

## 📄 License

This project is for educational and demonstration purposes.
