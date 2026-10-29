"""
Entry point for GoDrive executable.
"""
import logging

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)

if __name__ == "__main__":
    try:
        # Import and run GoDrive main function
        import GoDrive
        GoDrive.main()
    except KeyboardInterrupt:
        print("\n👋 GoDrive stopped by user.")
    except Exception as e:
        print(f"❌ Fatal error: {e}")
        logging.exception("Fatal error in main")
