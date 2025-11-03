"""
Automatic Kite Access Token Refresher

Handles automatic token refresh when expired.
Integrates with the main bot to maintain 24/7 operation.
"""

import os
import logging
from datetime import datetime, time
from pathlib import Path
import re
from typing import Optional


class TokenRefresher:
    """
    Automatic token refresh handler

    Features:
    - Detects token expiry
    - Auto-refreshes using credentials
    - Updates .env file
    - Notifies via Telegram
    """

    def __init__(self, config):
        """
        Initialize token refresher

        Args:
            config: Config object
        """
        self.config = config
        self.logger = logging.getLogger(__name__)

        self.api_key = config.kite_api_key
        self.api_secret = config.kite_api_secret

        # Check if auto-refresh is possible
        self.username = os.getenv('KITE_USERNAME')
        self.password = os.getenv('KITE_PASSWORD')
        self.totp_secret = os.getenv('KITE_TOTP_SECRET')

        self.can_auto_refresh = bool(self.username and self.password)

        if self.can_auto_refresh:
            self.logger.info("✅ Auto-refresh enabled (credentials found)")
        else:
            self.logger.warning("⚠️  Auto-refresh disabled (add KITE_USERNAME, KITE_PASSWORD to .env)")

    def is_token_expired(self) -> bool:
        """
        Check if current token is expired

        Tokens expire daily at 6:00 AM IST

        Returns:
            True if token likely expired
        """
        current_time = datetime.now().time()
        expiry_time = time(6, 0)  # 6:00 AM

        # If it's past 6 AM and before 7 AM, likely expired
        if expiry_time <= current_time < time(7, 0):
            return True

        return False

    async def refresh_token(self) -> Optional[str]:
        """
        Refresh access token automatically

        Returns:
            New access token or None if failed
        """
        if not self.can_auto_refresh:
            self.logger.error("Cannot auto-refresh: Missing credentials")
            return None

        self.logger.info("🔄 Attempting to refresh Kite access token...")

        try:
            # Import auth module
            from mch_bot.auth.kite_auth import KiteCreds, login_and_get_request_token, exchange_request_token_for_access

            # Create credentials
            creds = KiteCreds(
                api_key=self.api_key,
                api_secret=self.api_secret,
                username=self.username,
                password=self.password,
                totp_secret=self.totp_secret
            )

            # Get request token
            self.logger.info("📝 Logging in to Zerodha...")
            request_token = login_and_get_request_token(creds, timeout_ms=90000)

            # Exchange for access token
            self.logger.info("🔑 Generating access token...")
            access_token = exchange_request_token_for_access(creds, request_token)

            # Save to .env
            self._save_token_to_env(access_token)

            self.logger.info("✅ Token refreshed successfully!")

            return access_token

        except ImportError as e:
            self.logger.error(f"Auto-refresh requires: pip install playwright pyotp")
            self.logger.error(f"Then run: playwright install chromium")
            return None
        except Exception as e:
            self.logger.error(f"Token refresh failed: {e}")
            return None

    def _save_token_to_env(self, access_token: str):
        """
        Save access token to .env file

        Args:
            access_token: New access token
        """
        env_file = Path('.env')

        if not env_file.exists():
            self.logger.error(".env file not found")
            return

        # Read current content
        with open(env_file, 'r') as f:
            content = f.read()

        # Update or add token
        if 'KITE_ACCESS_TOKEN=' in content:
            content = re.sub(
                r'KITE_ACCESS_TOKEN=.*',
                f'KITE_ACCESS_TOKEN={access_token}',
                content
            )
        else:
            if not content.endswith('\n'):
                content += '\n'
            content += f'KITE_ACCESS_TOKEN={access_token}\n'

        # Write back
        with open(env_file, 'w') as f:
            f.write(content)

        self.logger.info("💾 Token saved to .env file")

    async def check_and_refresh_if_needed(self, kite_instance) -> bool:
        """
        Check token validity and refresh if needed

        Args:
            kite_instance: KiteConnect instance

        Returns:
            True if token is valid or successfully refreshed
        """
        try:
            # Try to make an API call
            profile = kite_instance.profile()
            self.logger.debug(f"Token valid for user: {profile.get('user_name')}")
            return True

        except Exception as e:
            error_msg = str(e).lower()

            # Check if it's a token error
            if 'token' in error_msg or 'session' in error_msg or 'authentication' in error_msg:
                self.logger.warning(f"⏰ Token expired or invalid: {e}")

                if self.can_auto_refresh:
                    # Attempt refresh
                    new_token = await self.refresh_token()

                    if new_token:
                        # Update kite instance
                        kite_instance.set_access_token(new_token)

                        # Update config (reload env)
                        try:
                            from dotenv import load_dotenv
                            load_dotenv(override=True)
                        except:
                            pass

                        self.logger.info("✅ Token refreshed and applied")
                        return True
                    else:
                        self.logger.error("❌ Token refresh failed")
                        return False
                else:
                    self.logger.error("❌ Token expired but auto-refresh not configured")
                    self.logger.error("   Run: python kite_token_generator.py")
                    return False
            else:
                # Different error
                self.logger.error(f"API error (not token-related): {e}")
                return False

    def get_manual_refresh_instructions(self) -> str:
        """
        Get instructions for manual token refresh

        Returns:
            Instructions string
        """
        return """
⏰ KITE ACCESS TOKEN EXPIRED

Your Kite access token has expired and auto-refresh is not configured.

To refresh manually:
1. Run: python kite_token_generator.py
2. Follow the instructions to get a new token
3. Restart the bot

OR configure auto-refresh:
1. Add to .env file:
   KITE_USERNAME=your_client_id
   KITE_PASSWORD=your_password
   KITE_TOTP_SECRET=your_2fa_secret (if applicable)

2. Install dependencies:
   pip install playwright pyotp
   playwright install chromium

3. Restart the bot
"""
