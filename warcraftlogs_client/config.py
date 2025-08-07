"""
Centralized configuration management for Warcraft Logs Analysis Tool.

This module handles loading, validation, and providing defaults for all configuration
settings used throughout the application.
"""

import json
import os
from typing import Dict, Any, Optional
from dataclasses import dataclass, field

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

@dataclass
class AppConfig:
    """Main application configuration."""
    api: ApiConfig
    role_thresholds: RoleThresholds = field(default_factory=RoleThresholds)
    
    # Optional settings with defaults
    cache_enabled: bool = True
    cache_dir: str = ".cache"
    reports_dir: str = "reports"
    
    # Character API settings
    default_region: str = "EU"
    default_server: str = "gehennas"

# Import the standardized error from common.errors
from .common.errors import ConfigurationError

class ConfigManager:
    """Manages application configuration loading and validation."""
    
    DEFAULT_CONFIG_FILE = "config.json"
    
    def __init__(self, config_file: Optional[str] = None):
        self.config_file = config_file or self.DEFAULT_CONFIG_FILE
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
        """Parse and validate raw configuration data."""
        # Validate required API settings
        required_fields = ["client_id", "client_secret", "report_id"]
        missing_fields = [field for field in required_fields if not raw_config.get(field)]
        
        if missing_fields:
            raise ConfigurationError(
                f"Missing required configuration fields: {', '.join(missing_fields)}"
            )
        
        # Create API config
        api_config = ApiConfig(
            client_id=raw_config["client_id"],
            client_secret=raw_config["client_secret"],
            report_id=raw_config["report_id"]
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
            default_region=raw_config.get("default_region", "EU"),
            default_server=raw_config.get("default_server", "gehennas")
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
        "role_thresholds": {
            "healer_min_healing": config.role_thresholds.healer_min_healing,
            "tank_min_taken": config.role_thresholds.tank_min_taken,
            "tank_min_mitigation": config.role_thresholds.tank_min_mitigation
        },
        "cache_enabled": config.cache_enabled,
        "cache_dir": config.cache_dir,
        "reports_dir": config.reports_dir,
        "default_region": config.default_region,
        "default_server": config.default_server
    }

def get_app_config(config_file: Optional[str] = None) -> AppConfig:
    """Get the typed application configuration."""
    manager = get_config_manager(config_file)
    return manager.load()
