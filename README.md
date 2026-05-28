# PDF OCR Tool

Extract text from scanned PDF books using Google's Document AI.  
Put a PDF in → get a `.txt` and `.md` file out.

---

## What You Need

- A **Mac** with [Homebrew](https://brew.sh/) installed
- A **Google account** (any Gmail works)
- A **credit card** for Google Cloud signup (you get **$300 free credits** — processing 44 books costs ~$20)

---

## Part 1: Google Cloud Console Setup

> **Do all of these steps in your browser.** You won't need the terminal until Part 2.

### Step 1. Create a Google Cloud Account

*Skip this if you already have a Google Cloud account.*

1. Go to [cloud.google.com](https://cloud.google.com)
2. Click **"Get started for free"**
3. Sign in with your Google account
4. Enter your billing information
   - You get **$300 in free credits** for 90 days
   - You will **not** be charged automatically — Google requires you to manually upgrade before any charges apply
5. You should land on the **Google Cloud Console** dashboard

### Step 2. Create a New Project

*Every resource in Google Cloud belongs to a project. If you are starting fresh and don't have a project yet, you must create one first.*

1. At the very top of the page (on the blue bar next to "Google Cloud"), click the **project dropdown menu**.
   * *If you are completely new, the dropdown might say "Select a project" or show a default first project like "My First Project".*
2. In the modal that opens, click **"New Project"** in the top right.
3. Enter a project name (e.g., `lit-ocr`).
4. Click **Create**.
5. Wait a few seconds for the creation process to complete. 
6. Click the project dropdown at the top again and **select your newly created project** so that it is active.

> 📝 **Write this down — Project ID**  
> The Project ID is shown on the "New Project" page below the name field while creating the project. **It is NOT the same as the project name** — Google often adds a number suffix (e.g., you type `lit-ocr` but the ID becomes `lit-ocr-438201`).
>
> **If you missed it**, you can find your Project ID anytime:
> - **Option A:** Click the **project dropdown** at the top of any Cloud Console page — the ID is shown in the second column
> - **Option B:** Go to [Project Settings](https://console.cloud.google.com/iam-admin/settings) — the Project ID is displayed on that page
> - **Option C:** In your terminal (after installing gcloud in Part 2), run `gcloud projects list`
>
> Write it down — you'll need it later.

### Step 3. Enable the Required APIs

You need to turn on two services:

1. **Document AI API:**
   - Go to: [Enable Document AI API](https://console.cloud.google.com/apis/library/documentai.googleapis.com)
   - Click **Enable**

2. **Cloud Storage API:**
   - Go to: [Enable Cloud Storage API](https://console.cloud.google.com/apis/library/storage.googleapis.com)
   - Click **Enable**

### Step 4. Create the OCR Processor

This creates the "engine" that will read your scanned PDFs.

1. Go to: [Document AI Processors](https://console.cloud.google.com/ai/document-ai/processors)
2. Click **"Explore Processors"** or **"Create Processor"** at the top of the page.
   * ⚠️ **Do NOT choose "Create custom processor"** if it is shown as a separate option. Custom processors are for training your own machine learning models from scratch, which requires uploading and labeling datasets. You do not need this!
3. Look in the gallery under the **General** (or pre-trained) category.
4. Locate the card for **"Enterprise Document OCR"** (or **"Document OCR"**) and click the **"Create Processor"** button on that card. A "Create Processor" flyout menu will slide out from the right side.
5. Enter a **Processor name** of your choice (this is just a display name for your convenience—we recommend `book-ocr`, but you can use anything).
6. Set the region to **US** (or **EU** if you're in Europe).
7. Click **Create** at the bottom of the flyout.

> 📝 **Write this down — Processor ID**  
> After creation, you'll be taken to the processor details page. The **Processor ID** is shown near the top — it's a hex string like `a1b2c3d4e5f67890`.
>
> **If you missed it**, go back to [Document AI Processors](https://console.cloud.google.com/ai/document-ai/processors), click on your processor, and the ID is displayed on the details page (also visible in the URL after `/processors/`).
>
> Write it down — you'll need it later.

### Step 5. Create a Storage Bucket

This is temporary storage where your PDFs are uploaded for processing.

1. Go to: [Cloud Storage](https://console.cloud.google.com/storage/browser)
2. Click **"Create"**
3. Enter a bucket name — use your Project ID followed by `-lit-ocr`
   - Example: `lit-ocr-438201-lit-ocr`
   - Bucket names must be globally unique
4. Location type: **Region**
5. Pick a region: **us-central1** (or any US region)
6. Leave everything else as default
7. Click **Create**
8. If prompted about "public access prevention," click **Confirm**

> 📝 **Write this down — Bucket Name**  
> You'll need the exact bucket name later (e.g., `lit-ocr-438201-lit-ocr`).

### Step 6. Add Lab Members (Admin Only)

*Skip this if you're the only user.*

For each lab member who needs access:

1. Go to: [IAM & Admin](https://console.cloud.google.com/iam-admin/iam)
2. Click **"Grant Access"**
3. In the "New principals" field, enter the lab member's **Google email address**
4. Click **"Select a role"** → search and add: **Document AI Editor**
5. Click **"Add another role"** → search and add: **Storage Object Admin**
6. Click **Save**
7. Repeat for each lab member

**✅ You're done with the browser! Close the console and open your terminal.**

---

## Part 2: Terminal Setup

> **Do all of these steps in your terminal.** You won't need the browser again.

### Step 1. Install Homebrew & Google Cloud CLI

#### 1. Check & Install Homebrew (If not already installed)
This script uses Homebrew to manage your local Google Cloud CLI tools.

* **Check if you have it**: Run `which brew` in your terminal. If it prints a path (like `/opt/homebrew/bin/brew`), you are good to go.
* **If it is NOT installed**: Copy and paste the following command into your terminal to install it:
  ```bash
  /bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"
  ```
  *After installation is complete, close and restart your terminal.*

#### 2. Install the Google Cloud CLI
Once Homebrew is ready, run this command to install the Google Cloud tools:

```bash
brew install google-cloud-sdk
```

This may take a few minutes.

### Step 2. Log In

Run both of these commands. Each one will open a browser window — sign in with the same Google account you used in Part 1.

```bash
gcloud auth login
```

```bash
gcloud auth application-default login
```

### Step 3. Set Your Project & Set ADC Quota Project

Replace `YOUR_PROJECT_ID` with the Project ID you wrote down in Part 1 (e.g., `lit-ocr-438201`):

```bash
# 1. Set the active CLI project
gcloud config set project YOUR_PROJECT_ID

# 2. Set the Application Default Credentials (ADC) quota project
# This avoids unexpected quota warning messages and ensures local Python scripts can bill/access your project.
gcloud auth application-default set-quota-project YOUR_PROJECT_ID
```

> **Forgot your Project ID?** Run `gcloud projects list` to see all your projects and their IDs.

### Step 4. Get the OCR Tool

Navigate to where you want the tool and get the files:

```bash
cd ~/Vibe/lit-ocr
```

*If you got this from a colleague, just make sure you have the `ocr.py`, `ocr.sh`, and `requirements.txt` files.*

### Step 5. Set Up Python

```bash
/opt/homebrew/bin/python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

> **Note:** If `/opt/homebrew/bin/python3` doesn't work, try just `python3 -m venv .venv`

### Step 6. Configure the Tool

```bash
python ocr.py --setup
```

This will ask you for the values you configured in Part 1:
- **Project ID** (e.g., `lit-ocr-438201`)
- **Processor ID** (e.g., `a1b2c3d4e5f67890`)
- **Bucket name** (e.g., `lit-ocr-438201-lit-ocr`)
- **Processor region** (defaults to `us`—just press **Enter** to accept the default, or type `eu` if you created your processor in Europe)

It will test the connections and save everything to `config.json`.

**✅ Setup complete! You're ready to OCR.**

---

## Part 3: How to Use

### Quick Start

```bash
cd ~/Vibe/lit-ocr
source .venv/bin/activate

# Process a single PDF
python ocr.py "path/to/My Book.pdf"
```

Or use the shortcut (no need to activate the virtual environment):

```bash
./ocr.sh "path/to/My Book.pdf"
```

### Process Multiple Files

```bash
# All PDFs in a specific folder
./ocr.sh ~/Desktop/my_scans/

# All PDFs in the default lit/ folder
./ocr.sh --all
```

> 💡 **MacBook Users: Prevent Sleep During Long Runs**  
> Large runs (like `--all`) can take 1–2 hours. If your MacBook goes to sleep or you close the lid, processing will pause.
>
> You can keep your Mac awake automatically until processing is complete by running the command with macOS's built-in `caffeinate` tool (remember to keep your laptop lid open!):
>
> ```bash
> caffeinate -i ./ocr.sh --all
> ```
> Once processing is finished, `caffeinate` will terminate automatically and your Mac will sleep normally.

### Where to Find Output

After processing, your files appear in:

```
output/
├── txt/
│   └── My Book.txt      ← Plain text
└── md/
    └── My Book.md       ← Markdown with page markers
```

Output filenames match the original PDF name.

### Other Commands

```bash
# Preview what would happen (no actual processing)
./ocr.sh --all --dry-run

# Resume an interrupted run
./ocr.sh --resume

# Clean up temporary files and cloud storage
./ocr.sh --cleanup
```

---

## Cost Reference

| Pages | Cost |
|---|---|
| First 1,000 per month | **Free** |
| 300 pages (1 typical book) | ~$0.45 |
| 1,000 pages | $1.50 |
| 10,000 pages | $15.00 |
| 20,000 pages (44 books) | ~$28.50 |

---

## Troubleshooting

| Problem | Solution |
|---|---|
| `gcloud: command not found` | Run `brew install google-cloud-sdk` and restart your terminal |
| `PERMISSION_DENIED` | Run `gcloud auth login` and `gcloud auth application-default login` again |
| `config.json not found` | Run `python ocr.py --setup` |
| `Processor not found` | Check the Processor ID in config.json matches what's shown in Cloud Console |
| `ModuleNotFoundError` | Activate the virtual environment first: `source .venv/bin/activate` then `pip install -r requirements.txt` |
| `Quota exceeded` | Wait a minute and try again. Google limits to 5 batch operations at once. |
| Script hangs during processing | Large books take time — a batch of 5,000 pages may take 30-60 minutes. Check terminal for progress updates. |
| `Bucket not found` | Make sure the bucket name in config.json exactly matches what you created in Cloud Console (no `gs://` prefix) |

---

## FAQ

**How long does it take?**  
About 1-3 minutes per 100 pages, depending on batch size. A single 300-page book typically takes 5-15 minutes. Processing 44 books takes 1-2 hours.

**Can I process non-English books?**  
Yes. Google Document AI automatically detects the language.

**What if it fails halfway through?**  
Run `./ocr.sh --resume` to pick up where it left off.

**Can I change the chunk size?**  
Yes. Edit `config.json` and change `max_pages_per_chunk` (default: 200, max: 200 for Document AI).

**Do I need to clean up after processing?**  
It's recommended. Run `./ocr.sh --cleanup` to delete temporary files from Google Cloud Storage. Your output files are preserved.

**What's the maximum file size?**  
1 GB per PDF for batch processing. The script automatically splits books longer than 200 pages.

---

## File Overview

```
├── README.md               This guide
├── ocr.py                  The OCR processing script
├── ocr.sh                  One-command shortcut wrapper
├── requirements.txt        Python dependencies
├── config.json             Your GCP settings (auto-created by --setup)
├── lit/                    Default folder for input PDFs
├── output/txt/             Plain text output files
└── output/md/              Markdown output files
```
