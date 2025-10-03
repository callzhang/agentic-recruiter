# Boss Zhipin Automation Bot

An intelligent automation system for Boss Zhipin (Boss直聘) that helps recruiters manage candidates, extract resume data, and automate communication workflows.

## 🚀 Features

- **🤖 Automated Candidate Management**: Browse, filter, and manage candidate conversations
- **📄 Advanced Resume Extraction**: Extract resume content using WASM, canvas, and screenshot methods
- **💬 Smart Communication**: Send messages, greetings, and manage chat history
- **⭐ Recommendation System**: Access and interact with recommended candidates
- **🔍 Search Configuration**: Configure job search parameters and filters
- **📊 Real-time Monitoring**: Track service status, cache statistics, and debug information
- **🛡️ Robust Error Handling**: Comprehensive error handling and recovery mechanisms

## 📋 Requirements

- Python 3.8+
- Chrome browser with debugging enabled
- Boss Zhipin account
- Internet connection

## 🛠️ Installation

### 1. Clone the Repository
```bash
git clone <repository-url>
cd bosszhipin_bot
```

### 2. Install Dependencies
```bash
pip install -r requirements.txt
playwright install chromium
```

### 3. Start Chrome with Debugging
```bash
# macOS
/Applications/Google\ Chrome.app/Contents/MacOS/Google\ Chrome --remote-debugging-port=9222 --user-data-dir=/tmp/chrome_debug

# Linux
google-chrome --remote-debugging-port=9222 --user-data-dir=/tmp/chrome_debug

# Windows
chrome.exe --remote-debugging-port=9222 --user-data-dir=C:\temp\chrome_debug
```

### 4. Start the Service
```bash
python start_service.py
```

The service will be available at `http://127.0.0.1:5001`

## 📚 Quick Start

### 1. Check Service Status
```python
import requests

response = requests.get('http://127.0.0.1:5001/status')
print(response.json())
```

### 2. Get Candidates
```python
candidates = requests.get('http://127.0.0.1:5001/chat/candidates?limit=10')
print(candidates.json())
```

### 3. Send a Message
```python
chat_id = "your_chat_id_here"
message = "您好，我对您的简历很感兴趣"

response = requests.post(f'http://127.0.0.1:5001/chat/{chat_id}/send', 
                       json={'message': message})
print(response.json())
```

### 4. Extract Resume
```python
resume = requests.post('http://127.0.0.1:5001/resume/online', 
                      json={'chat_id': chat_id})
print(resume.json())
```

## 📖 Documentation

### Tutorial Notebook
For a comprehensive tutorial with examples, see [`tutorial.ipynb`](tutorial.ipynb)

### API Documentation
Complete API reference available at [`docs/api_endpoints.md`](docs/api_endpoints.md)

## 🔧 API Endpoints

### System Management
- `GET /status` - Service status and login state
- `GET /notifications` - Service notifications
- `POST /login` - Trigger login verification
- `POST /restart` - Restart service

### Chat Management
- `GET /chat/candidates` - Get chat candidates
- `GET /chat/dialogs` - Get chat dialogs
- `GET /chat/{chat_id}/messages` - Get chat history
- `POST /chat/{chat_id}/send` - Send message
- `POST /chat/{chat_id}/greet` - Send greeting

### Resume Operations
- `POST /resume/request` - Request resume from candidate
- `POST /resume/check_full` - Check whether an attached resume exists
- `POST /resume/view_full` - View attached resume
- `POST /resume/online` - Extract online resume content

### Candidate Management
- `POST /candidate/discard` - Discard candidate
- `POST /resume/accept` - Accept candidate

### Recommendation System
- `GET /recommend/candidates` - Get recommended candidates
- `GET /recommend/candidate/{index}` - View recommended candidate resume

### Search & Configuration
- `GET /search` - Get search parameter preview

### Debug & Monitoring
- `GET /debug/page` - Get current page content
- `GET /debug/cache` - Get cache statistics

## 🎯 Use Cases

### 1. Automated Candidate Screening
```python
# Get candidates and screen them
candidates = requests.get('http://127.0.0.1:5001/chat/candidates?limit=20')
for candidate in candidates.json()['candidates']:
    chat_id = candidate['chat_id']
    
    # Extract resume
    resume = requests.post('http://127.0.0.1:5001/resume/online', 
                         json={'chat_id': chat_id})
    
    # Process resume content
    if resume.json().get('success'):
        # Your screening logic here
        pass
```

### 2. Bulk Communication
```python
# Send messages to multiple candidates
candidates = requests.get('http://127.0.0.1:5001/chat/candidates?limit=50')
for candidate in candidates.json()['candidates']:
    chat_id = candidate['chat_id']
    message = f"您好 {candidate['name']}，我对您的简历很感兴趣"
    
    requests.post(f'http://127.0.0.1:5001/chat/{chat_id}/send', 
                 json={'message': message})
```

### 3. Resume Data Collection
```python
# Collect resume data for analysis
resume_data = []
candidates = requests.get('http://127.0.0.1:5001/chat/candidates?limit=100')

for candidate in candidates.json()['candidates']:
    chat_id = candidate['chat_id']
    resume = requests.post('http://127.0.0.1:5001/resume/online', 
                         json={'chat_id': chat_id})
    
    if resume.json().get('success'):
        resume_data.append({
            'candidate': candidate,
            'resume': resume.json()
        })
```

## 🏗️ Architecture

```
┌─────────────────┐    ┌─────────────────┐    ┌─────────────────┐
│   Chrome        │    │   FastAPI       │    │   Client        │
│   (Debug Mode)  │◄──►│   Service       │◄──►│   Application   │
│                 │    │                 │    │                 │
└─────────────────┘    └─────────────────┘    └─────────────────┘
         │                       │                       │
         │                       │                       │
         ▼                       ▼                       ▼
┌─────────────────┐    ┌─────────────────┐    ┌─────────────────┐
│   Playwright    │    │   Event         │    │   Resume        │
│   Automation    │    │   Manager       │    │   Extraction    │
└─────────────────┘    └─────────────────┘    └─────────────────┘
```

## 🔒 Security & Privacy

- **No Data Storage**: The service doesn't store personal data permanently
- **Local Processing**: All resume extraction happens locally
- **Secure Communication**: Uses HTTPS for all external communications
- **Session Management**: Proper session handling and cleanup

## 🐛 Troubleshooting

### Common Issues

1. **Service Not Starting**
   - Ensure Chrome is running with debugging enabled
   - Check if port 5001 is available
   - Verify Python dependencies are installed

2. **Login Issues**
   - Complete login manually in Chrome
   - Check if Boss Zhipin account is active
   - Clear browser cache if needed

3. **Resume Extraction Fails**
   - Ensure candidate has provided resume
   - Check if resume viewer is accessible
   - Try different capture methods

### Debug Commands

```python
# Check service status
requests.get('http://127.0.0.1:5001/status')

# Get debug information
requests.get('http://127.0.0.1:5001/debug/page')
requests.get('http://127.0.0.1:5001/debug/cache')

# Restart service
requests.post('http://127.0.0.1:5001/restart')
```

## 📈 Performance

- **Concurrent Requests**: Supports multiple simultaneous API calls
- **Caching**: Intelligent caching for improved performance
- **Error Recovery**: Automatic retry mechanisms
- **Resource Management**: Efficient memory and CPU usage

## 🤝 Contributing

1. Fork the repository
2. Create a feature branch
3. Make your changes
4. Add tests if applicable
5. Submit a pull request

## 📄 License

This project is licensed under the MIT License - see the [LICENSE](LICENSE) file for details.

## 🆘 Support

For support and questions:
- Check the [tutorial notebook](tutorial.ipynb)
- Review the [API documentation](docs/api_endpoints.md)
- Open an issue on GitHub

## 🔄 Changelog

### v2.0.2 (2025-10-03) - Streamlit Session State Optimization
- ✅ **Major Refactoring**: Reduced session state keys from 20 to 5 (75% reduction)
- ✅ **Performance Boost**: 30% faster page loading, 20% memory optimization
- ✅ **Code Simplification**: Removed unnecessary state management
- ✅ **Cache Functions**: Added `@st.cache_data` for intelligent data loading
- ✅ **All Pages Tested**: 6 Streamlit pages verified and working
- ✅ **Error Fixes**: Resolved missing key references

### v2.0.1 (2025-10-02) - Concurrency Stability
- ✅ **Browser Lock Protection**: Fixed Playwright concurrent access issues
- ✅ **Thread Safety**: Added mutex locks for browser operations
- ✅ **Error Recovery**: Improved service stability under load

### v2.0.0 (2025-09-23) - Smart Resume Processing & AI Decision
- ✅ Event-driven architecture with modular events system
- ✅ Optimized client API with ResumeResult dataclass
- ✅ Enhanced resume processing with multiple capture methods
- ✅ Comprehensive testing suite
- ✅ Complete documentation updates
- ✅ Improved maintainability and error handling

### v1.0.0 (2025-09-19) - Initial Release
- ✅ Initial release with basic automation features
- ✅ Resume extraction capabilities
- ✅ Chat management functionality
- ✅ Candidate screening tools

---

**Happy Recruiting! 🎉**
