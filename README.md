# Universal Website Scraper (MVP)

## 1. How to Set Up and Run the Project

Make the startup script executable:

```bash
chmod +x run.sh
```

Then run the project:

```bash
./run.sh
```

### Environment details
- `run.sh` automatically:
  - Activates the Python virtual environment  
  - Installs dependencies  
  - Installs Playwright Chromium browser (`playwright install chromium`)  
  - Starts the FastAPI server  

No manual steps outside `chmod +x run.sh` and `./run.sh` are required.

---

## 2. Primary URLs Used for Testing

### **1. Wikipedia — Static HTML Page**
URL: https://en.wikipedia.org/wiki/Artificial_intelligence  
- Large static content  
- No JavaScript required  
- Good baseline for static-section extraction  

### **2. Vercel.com — JS-heavy Marketing Page**
URL: https://vercel.com/  
- Interactive tabs & dynamic sections  
- Used to test JS rendering, scrolling, and click simulation  

### **3. Hacker News — Pagination Test**
URL: https://news.ycombinator.com/  
- Table-based layout (no semantic tags)  
- Requires fallback parsing logic  
- Pagination tested up to depth 3  

---

## 3. Known Limitations / Caveats

- Extremely JS-heavy websites may render slowly due to Playwright overhead.  
- Some complex SPA frameworks delay content beyond network idle events.  
- HTML extraction truncates raw HTML at 3000 characters to avoid oversized payloads.  
- Section grouping is heuristic-based, so structure may vary across unusual sites.  

---

# Additional Technical Details
## Overview

This project implements a hybrid static + JS web scraper using **FastAPI**, **Playwright**, and **BeautifulSoup**. It extracts structured content into section-aware JSON that includes:

- Metadata  
- Sections  
- Headings  
- Text  
- Links  
- Lists  
- Tables  
- Images  
- Raw HTML (truncated)  
- JS interactions (clicks, scrolls, pages visited)

## Architecture

```
Frontend (HTML/CSS/JS)
        ↓
POST /scrape
        ↓
Static Fetch → BeautifulSoup Parsing
        ↓
If insufficient → Playwright JS Rendering
        ↓
Final Structured JSON
```

## Tech Stack
- Python 3  
- FastAPI  
- httpx  
- Playwright (Chromium)  
- BeautifulSoup (lxml)  
- Vanilla JS Frontend  

## Project Structure
```
├── main.py
├── run.sh
├── requirements.txt
├── templates/
│   └── index.html
└── README.md
```

## Author
**Made by Uday Srivastava**
