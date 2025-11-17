"""Pydantic schemas for configuration validation"""

from typing import List, Literal, Optional, Dict, Any
from pydantic import BaseModel, Field, field_validator, model_validator


class PlatformConfig(BaseModel):
    """Platform configuration"""
    type: Literal["homeassistant", "homey", "homey_pro"] = Field(
        ...,
        description="Smart home platform type"
    )


class HomeAssistantConfig(BaseModel):
    """Home Assistant connection configuration"""
    url: str = Field(default="", description="Home Assistant URL")
    token: str = Field(default="", description="Long-lived access token")

    @field_validator('url')
    @classmethod
    def validate_url(cls, v: str) -> str:
        """Validate URL format"""
        if v and not v.startswith(('http://', 'https://')):
            raise ValueError("URL must start with http:// or https://")
        if v and v.endswith('/'):
            v = v[:-1]  # Remove trailing slash
        return v


class HomeyConfig(BaseModel):
    """Homey Pro connection configuration"""
    url: str = Field(default="", description="Homey API URL")
    token: str = Field(default="", description="Homey bearer token")

    @field_validator('url')
    @classmethod
    def validate_url(cls, v: str) -> str:
        """Validate URL format"""
        if v and not v.startswith(('http://', 'https://')):
            raise ValueError("URL must start with http:// or https://")
        if v and v.endswith('/'):
            v = v[:-1]  # Remove trailing slash
        return v


class DataCollectionSensorsConfig(BaseModel):
    """Sensor configuration for data collection"""
    temperature: List[str] = Field(default_factory=list)
    light: List[str] = Field(default_factory=list)
    motion: List[str] = Field(default_factory=list)
    power: List[str] = Field(default_factory=list)


class DataCollectionConfig(BaseModel):
    """Data collection configuration"""
    interval_seconds: int = Field(
        default=300,
        ge=10,
        le=3600,
        description="Collection interval in seconds (10-3600)"
    )
    sensors: DataCollectionSensorsConfig = Field(
        default_factory=DataCollectionSensorsConfig
    )


class WeatherConfig(BaseModel):
    """Weather API configuration"""
    enabled: bool = Field(default=True)
    location: str = Field(default="Berlin, DE")
    api_key: Optional[str] = Field(default=None)


class EnergyPricesConfig(BaseModel):
    """Energy prices API configuration"""
    enabled: bool = Field(default=False)
    provider: Literal["awattar", "tibber"] = Field(default="awattar")
    api_key: Optional[str] = Field(default=None)


class ExternalDataConfig(BaseModel):
    """External data sources configuration"""
    weather: WeatherConfig = Field(default_factory=WeatherConfig)
    energy_prices: EnergyPricesConfig = Field(default_factory=EnergyPricesConfig)


class ModelFeaturesConfig(BaseModel):
    """ML model features configuration"""
    type: Literal["random_forest", "gradient_boosting"] = Field(
        default="random_forest"
    )
    retrain_interval_hours: int = Field(
        default=24,
        ge=1,
        le=168,
        description="Retrain interval in hours (1-168)"
    )
    min_training_samples: int = Field(
        default=100,
        ge=10,
        description="Minimum samples required for training"
    )
    features: List[str] = Field(default_factory=list)


class EnergyOptimizerConstraintsConfig(BaseModel):
    """Energy optimizer constraints"""
    min_temperature: float = Field(
        default=16.0,
        ge=10.0,
        le=25.0,
        description="Minimum temperature in Celsius (10-25)"
    )
    max_temperature: float = Field(
        default=25.0,
        ge=10.0,
        le=30.0,
        description="Maximum temperature in Celsius (10-30)"
    )
    comfort_priority: float = Field(
        default=0.7,
        ge=0.0,
        le=1.0,
        description="Comfort priority (0-1)"
    )

    @model_validator(mode='after')
    def validate_temperature_range(self) -> 'EnergyOptimizerConstraintsConfig':
        """Ensure min_temperature < max_temperature"""
        if self.min_temperature >= self.max_temperature:
            raise ValueError("min_temperature must be less than max_temperature")
        return self


class EnergyOptimizerConfig(BaseModel):
    """Energy optimizer configuration"""
    type: Literal["optimization"] = Field(default="optimization")
    target: Literal["minimize_cost", "minimize_consumption", "balance"] = Field(
        default="balance"
    )
    constraints: EnergyOptimizerConstraintsConfig = Field(
        default_factory=EnergyOptimizerConstraintsConfig
    )


class ModelsConfig(BaseModel):
    """ML models configuration"""
    lighting: ModelFeaturesConfig = Field(default_factory=ModelFeaturesConfig)
    heating: ModelFeaturesConfig = Field(default_factory=lambda: ModelFeaturesConfig(
        type="gradient_boosting",
        min_training_samples=200
    ))
    energy_optimizer: EnergyOptimizerConfig = Field(
        default_factory=EnergyOptimizerConfig
    )


class DecisionEngineRuleConfig(BaseModel):
    """Decision engine rule configuration"""
    name: str
    condition: str
    action: str


class DecisionEngineConfig(BaseModel):
    """Decision engine configuration"""
    mode: Literal["auto", "manual", "learning"] = Field(
        default="learning",
        description="Operating mode: auto (execute), manual (suggest), learning (collect only)"
    )
    confidence_threshold: float = Field(
        default=0.7,
        ge=0.0,
        le=1.0,
        description="Minimum confidence for action execution (0-1)"
    )
    safety_checks: bool = Field(
        default=True,
        description="Enable safety checks"
    )
    rules: List[DecisionEngineRuleConfig] = Field(default_factory=list)


class MLAutoTrainerConfig(BaseModel):
    """ML auto-trainer configuration"""
    enabled: bool = Field(default=True)
    run_hour: int = Field(
        default=2,
        ge=0,
        le=23,
        description="Hour of day to run training (0-23)"
    )
    min_samples_lighting: int = Field(
        default=100,
        ge=10,
        description="Minimum samples for lighting model"
    )
    min_samples_heating: int = Field(
        default=200,
        ge=10,
        description="Minimum samples for heating model"
    )


class DatabaseConfig(BaseModel):
    """Database configuration"""
    type: Literal["sqlite"] = Field(default="sqlite")
    path: str = Field(default="data/ki_system.db")
    retention_days: int = Field(
        default=90,
        ge=1,
        le=365,
        description="Data retention in days (1-365)"
    )


class LoggingConfig(BaseModel):
    """Logging configuration"""
    level: Literal["DEBUG", "INFO", "WARNING", "ERROR"] = Field(default="INFO")
    path: str = Field(default="logs/ki_system.log")
    max_size_mb: int = Field(
        default=100,
        ge=1,
        le=1000,
        description="Maximum log file size in MB (1-1000)"
    )


class KISystemConfig(BaseModel):
    """Complete KI-System configuration schema"""
    platform: PlatformConfig
    home_assistant: Optional[HomeAssistantConfig] = None
    homey: Optional[HomeyConfig] = None
    data_collection: DataCollectionConfig = Field(default_factory=DataCollectionConfig)
    external_data: ExternalDataConfig = Field(default_factory=ExternalDataConfig)
    models: ModelsConfig = Field(default_factory=ModelsConfig)
    decision_engine: DecisionEngineConfig = Field(default_factory=DecisionEngineConfig)
    ml_auto_trainer: MLAutoTrainerConfig = Field(default_factory=MLAutoTrainerConfig)
    database: DatabaseConfig = Field(default_factory=DatabaseConfig)
    logging: LoggingConfig = Field(default_factory=LoggingConfig)

    @model_validator(mode='after')
    def validate_platform_config(self) -> 'KISystemConfig':
        """Validate that platform-specific config exists"""
        platform_type = self.platform.type.lower()

        if platform_type in ['homeassistant']:
            if not self.home_assistant:
                raise ValueError("home_assistant config required when platform.type is 'homeassistant'")
        elif platform_type in ['homey', 'homey_pro']:
            if not self.homey:
                raise ValueError("homey config required when platform.type is 'homey' or 'homey_pro'")

        return self

    model_config = {
        "extra": "allow",  # Allow extra fields for forward compatibility
        "validate_assignment": True  # Validate on assignment
    }
