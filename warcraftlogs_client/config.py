"""
Centralized configuration management for Warcraft Logs Analysis Tool.

This module handles loading, validation, and providing defaults for all configuration
settings used throughout the application.
"""

import json
import os
from typing import Dict, Any, Optional
from dataclasses import dataclass, field
from pathlib import Path

@dataclass
class RoleThresholds:
    """Configuration for role detection thresholds."""
    healer_min_healing: int = 50000
    tank_min_taken: int = 150000
    tank_min_mitigation: int = 40

@dataclass
class ApiConfig:
    """Configuration for Warcraft Logs API access."""
    client_id: str
    client_secret: str
    report_id: str
    guild_id: int = 774065

@dataclass
class AppConfig:
    """Main application configuration."""
    api: ApiConfig
    role_thresholds: RoleThresholds = field(default_factory=RoleThresholds)
    
    # Optional settings with defaults
    cache_enabled: bool = True
    cache_dir: str = ".cache"
    reports_dir: str = "reports"
    guild_logo: str = "logo.png"
    guild_name: str = ""
    guild_server: str = ""

    # Character API settings
    default_region: str = "EU"
    default_server: str = "gehennas"

    # Character profile
    character_name: str = ""
    character_server: str = ""
    character_region: str = "eu"
    wcl_api_url: str = "https://fresh.warcraftlogs.com/api/v2/client"

# Import the standardized error from common.errors
from .common.errors import ConfigurationError

class ConfigManager:
    """Manages application configuration loading and validation."""
    
    def __init__(self, config_file: Optional[str] = None):
        from . import paths
        self.config_file = config_file or str(paths.get_config_path())
        self._config: Optional[AppConfig] = None
    
    def load(self) -> AppConfig:
        """Load and validate configuration from file."""
        if self._config is not None:
            return self._config
            
        if not os.path.exists(self.config_file):
            raise ConfigurationError(
                f"Configuration file '{self.config_file}' not found. "
                "Please create it with your Warcraft Logs API credentials."
            )
        
        try:
            with open(self.config_file, "r") as f:
                raw_config = json.load(f)
        except json.JSONDecodeError as e:
            raise ConfigurationError(f"Invalid JSON in config file: {e}")
        except IOError as e:
            raise ConfigurationError(f"Cannot read config file: {e}")
        
        self._config = self._parse_config(raw_config)
        return self._config
    
    def _parse_config(self, raw_config: Dict[str, Any]) -> AppConfig:
        """Parse and validate raw configuration data.

        Credentials are resolved in order: environment variables > config file.
        """
        client_id = os.environ.get("WARCRAFTLOGS_CLIENT_ID") or raw_config.get("client_id")
        client_secret = os.environ.get("WARCRAFTLOGS_CLIENT_SECRET") or raw_config.get("client_secret")
        report_id = os.environ.get("WARCRAFTLOGS_REPORT_ID") or raw_config.get("report_id")

        missing = []
        if not client_id:
            missing.append("client_id (or WARCRAFTLOGS_CLIENT_ID env var)")
        if not client_secret:
            missing.append("client_secret (or WARCRAFTLOGS_CLIENT_SECRET env var)")
        if not report_id:
            missing.append("report_id (or WARCRAFTLOGS_REPORT_ID env var)")

        if missing:
            raise ConfigurationError(
                f"Missing required configuration: {', '.join(missing)}"
            )

        guild_id = raw_config.get("guild_id", 774065)
        try:
            guild_id = int(guild_id)
        except (TypeError, ValueError):
            guild_id = 774065

        api_config = ApiConfig(
            client_id=client_id,
            client_secret=client_secret,
            report_id=report_id,
            guild_id=guild_id,
        )
        
        # Parse role thresholds with defaults
        role_thresholds_data = raw_config.get("role_thresholds", {})
        role_thresholds = RoleThresholds(
            healer_min_healing=role_thresholds_data.get("healer_min_healing", 50000),
            tank_min_taken=role_thresholds_data.get("tank_min_taken", 150000),
            tank_min_mitigation=role_thresholds_data.get("tank_min_mitigation", 40)
        )
        
        # Create main config with optional settings
        config = AppConfig(
            api=api_config,
            role_thresholds=role_thresholds,
            cache_enabled=raw_config.get("cache_enabled", True),
            cache_dir=raw_config.get("cache_dir", ".cache"),
            reports_dir=raw_config.get("reports_dir", "reports"),
            guild_logo=raw_config.get("guild_logo", "logo.png"),
            guild_name=raw_config.get("guild_name", ""),
            guild_server=raw_config.get("guild_server", ""),
            default_region=raw_config.get("default_region", "EU"),
            default_server=raw_config.get("default_server", "gehennas"),
            character_name=raw_config.get("character_name", ""),
            character_server=raw_config.get("character_server", ""),
            character_region=raw_config.get("character_region", "eu"),
            wcl_api_url=raw_config.get("wcl_api_url", "https://fresh.warcraftlogs.com/api/v2/client"),
        )
        
        return config
    
    def get_role_thresholds(self) -> Dict[str, Any]:
        """Get role thresholds in the format expected by legacy code."""
        config = self.load()
        return {
            "healer_min_healing": config.role_thresholds.healer_min_healing,
            "tank_min_taken": config.role_thresholds.tank_min_taken,
            "tank_min_mitigation": config.role_thresholds.tank_min_mitigation
        }

# Global config manager instance
_config_manager: Optional[ConfigManager] = None

def get_config_manager(config_file: Optional[str] = None) -> ConfigManager:
    """Get the global configuration manager instance."""
    global _config_manager
    if _config_manager is None or config_file is not None:
        _config_manager = ConfigManager(config_file)
    return _config_manager

def load_config(config_file: Optional[str] = None) -> Dict[str, Any]:
    """
    Load configuration and return in legacy format for backward compatibility.
    
    This function maintains compatibility with existing code while using
    the new configuration management system.
    """
    manager = get_config_manager(config_file)
    config = manager.load()
    
    # Return in legacy format
    return {
        "client_id": config.api.client_id,
        "client_secret": config.api.client_secret,
        "report_id": config.api.report_id,
        "guild_id": config.api.guild_id,
        "role_thresholds": {
            "healer_min_healing": config.role_thresholds.healer_min_healing,
            "tank_min_taken": config.role_thresholds.tank_min_taken,
            "tank_min_mitigation": config.role_thresholds.tank_min_mitigation
        },
        "guild_logo": config.guild_logo,
        "guild_name": config.guild_name,
        "guild_server": config.guild_server,
        "cache_enabled": config.cache_enabled,
        "cache_dir": config.cache_dir,
        "reports_dir": config.reports_dir,
        "default_region": config.default_region,
        "default_server": config.default_server,
        "character_name": config.character_name,
        "character_server": config.character_server,
        "character_region": config.character_region,
        "wcl_api_url": config.wcl_api_url,
    }

def get_app_config(config_file: Optional[str] = None) -> AppConfig:
    """Get the typed application configuration."""
    manager = get_config_manager(config_file)
    return manager.load()
