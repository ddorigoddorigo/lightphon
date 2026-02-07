# LightPhon Node Client

A Windows desktop application to connect your GPU to the AI Lightning network and earn Bitcoin (sats) by providing AI inference services.

## 📋 Requirements

Before running LightPhon, you need to install the following dependencies:

### 1. Visual C++ Redistributable

Download and install the latest **Microsoft Visual C++ Redistributable**:

- [Download VC++ Redistributable (x64)](https://aka.ms/vs/17/release/vc_redist.x64.exe)

Or install via winget:
```powershell
winget install Microsoft.VCRedist.2015+.x64
```

### 2. llama-server (llama.cpp)

Install **llama.cpp** which includes llama-server:

```powershell
winget install llama.cpp
```

After installation, verify it's installed correctly:
```powershell
llama-server --version
```

## 🚀 Installation

1. Download the latest `LightPhon-Node.exe` from the [Releases](https://github.com/ddorigoddorigo/LightPhon/releases) page
2. Run the executable - no installation required!

## ⚙️ Configuration

On first run, you'll need to:

1. Select the folder containing your GGUF models
2. Choose which models to make available on the network

## 💡 How it Works

1. **Connect** - The app connects to the AI Lightning network
2. **Share Models** - Your selected AI models become available for users
3. **Earn Sats** - When users run inference on your models, you earn Bitcoin via Lightning Network

## 🔧 Troubleshooting

### "llama-server not found"
Make sure llama-server is installed and in your PATH:
```powershell
winget install llama.cpp
```

### "VCRUNTIME140.dll not found"
Install Visual C++ Redistributable:
```powershell
winget install Microsoft.VCRedist.2015+.x64
```

### "Connection failed"
- Check your internet connection
- Verify the server URL is correct
- Make sure your firewall allows the connection

## 📜 License

MIT License - See [LICENSE](LICENSE) for details.

## 🤝 Support

For issues and feature requests, please open an issue on GitHub.

