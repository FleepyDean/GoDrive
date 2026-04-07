# GoDrive

GoDrive is a Python application that interacts with the Telegram API to provide location-based services. It processes incoming messages, extracts pickup and drop-off locations and calculates travel distances.

## Setup Instructions

1. **Clone the Repository**
   ```bash
   git clone https://github.com/yourusername/godrive.git
   cd godrive
   ```

2. **Create a Virtual Environment**
   It is recommended to use a virtual environment to manage dependencies.
   ```bash
   python -m venv venv
   source venv/bin/activate  # On Windows use `venv\Scripts\activate`
   ```

3. **Install Dependencies**
   Install the required Python packages using pip.
   ```bash
   pip install -r requirements.txt
   ```

4. **Set Up Environment Variables**
   Create a `.env` file in the root directory of the project based on the `.env.example` file. Fill in the required API keys and other configuration settings.

## Obtaining API Keys

### Google API Key
1. Go to the [Google Cloud Console](https://console.cloud.google.com/).
2. Create a new project or select an existing project.
3. Navigate to the "APIs & Services" dashboard.
4. Click on "Enable APIs and Services" and enable the following APIs:
   - Geocoding API
   - Distance Matrix API
5. Go to "Credentials" and click on "Create Credentials" to generate an API key.
6. Copy the API key and add it to your `.env` file as `GOOGLE_MAPS_API_KEY`.

### Telegram API Key
1. Open the Telegram app and search for the "BotFather" bot.
2. Start a chat with BotFather and use the command `/newbot` to create a new bot.
3. Follow the instructions to set a name and username for your bot.
4. Once created, BotFather will provide you with a token. Copy this token.
5. Add the token to your `.env` file as `BOT_TOKEN`.

## Running the Application
To run the GoDrive application, execute the following command:
```bash
python src/GoDrive.py
```

## License
This project is licensed and any unauthorized usage or illegal activities will be taken action!