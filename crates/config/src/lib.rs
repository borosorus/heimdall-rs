//! Configuration management for Heimdall
//!
//! This crate provides functionality for managing the Heimdall configuration,
//! including loading, saving, updating, and deleting configuration settings.

/// Error types for the configuration module
pub mod error;

use crate::error::Error;
use clap::Parser;
use heimdall_common::{
    resources::llm::{LlmResponseFormat, DEFAULT_MODEL, OPENROUTER_API_BASE},
    utils::io::file::{delete_path, read_file, write_file},
};
use serde::{Deserialize, Serialize};
#[allow(deprecated)]
use std::env::home_dir;
use std::fmt;
use tracing::{debug, error, info};

/// Command line arguments for the configuration command
#[derive(Debug, Clone, Parser)]
#[clap(
    about = "Display and edit the current configuration",
    after_help = "For more information, read the wiki: https://jbecker.dev/r/heimdall-rs/wiki",
    override_usage = "heimdall config [OPTIONS]"
)]
pub struct ConfigArgs {
    /// The target key to update.
    #[clap(required = false, default_value = "")]
    key: String,

    /// The value to set the key to.
    #[clap(required = false, default_value = "")]
    value: String,
}

/// The [`Configuration`] struct represents the configuration of the CLI. All heimdall core modules
/// will attempt to read from this configuration when possible.
#[derive(Deserialize, Serialize)]
pub struct Configuration {
    /// The URL for the Ethereum RPC endpoint
    pub rpc_url: String,

    /// The URL for a local Ethereum RPC endpoint
    pub local_rpc_url: String,

    /// The API key for Etherscan services
    pub etherscan_api_key: String,

    /// The API key for Transpose services
    pub transpose_api_key: String,

    /// The API key for OpenRouter services
    pub openrouter_api_key: String,

    /// The default model to use for OpenRouter LLM calls (e.g., "openai/gpt-4o-mini")
    #[serde(default)]
    pub openrouter_model: String,

    /// The base URL of a custom OpenAI-compatible chat-completions API. Empty uses OpenRouter.
    #[serde(default)]
    pub llm_base_url: String,

    /// The API key for the custom OpenAI-compatible API. Empty sends no authorization header.
    #[serde(default)]
    pub llm_api_key: String,

    /// The model identifier to send to the custom OpenAI-compatible API.
    #[serde(default)]
    pub llm_model: String,

    /// The requested structured-output format. Empty means automatic fallback.
    #[serde(default)]
    pub llm_response_format: Option<LlmResponseFormat>,
}

impl Default for Configuration {
    fn default() -> Self {
        Configuration {
            rpc_url: "".to_string(),
            local_rpc_url: "http://localhost:8545".to_string(),
            etherscan_api_key: "".to_string(),
            transpose_api_key: "".to_string(),
            openrouter_api_key: "".to_string(),
            openrouter_model: "".to_string(),
            llm_base_url: "".to_string(),
            llm_api_key: "".to_string(),
            llm_model: "".to_string(),
            llm_response_format: None,
        }
    }
}

/// Redact a secret, preserving whether it was configured at all.
fn redact_secret(value: &str) -> String {
    if value.is_empty() {
        "<unset>".to_string()
    } else {
        "<redacted>".to_string()
    }
}

/// Redact credentials and the path/query of an RPC URL.
fn redact_rpc_url(value: &str) -> String {
    if value.is_empty() {
        return "<unset>".to_string();
    }

    let Some((scheme, rest)) = value.split_once("://") else {
        return "<redacted>".to_string();
    };
    let authority_end = rest.find(['/', '?', '#']).unwrap_or(rest.len());
    let raw_authority = &rest[..authority_end];
    let authority = raw_authority.rsplit_once('@').map_or(raw_authority, |(_, host)| host);
    let tail = &rest[authority_end..];
    let tail_is_sensitive = tail.contains('?') ||
        tail.contains('#') ||
        raw_authority.contains('@') ||
        tail.trim_matches('/').chars().any(|character| character != '/');

    if tail_is_sensitive {
        format!("{scheme}://{authority}/<redacted>")
    } else {
        format!("{scheme}://{authority}{tail}")
    }
}

/// Redact credentials and query parameters from an API endpoint while preserving its path.
fn redact_endpoint(value: &str) -> String {
    if value.is_empty() {
        return "<unset>".to_string();
    }

    let Some((scheme, rest)) = value.split_once("://") else {
        return "<redacted>".to_string();
    };
    let authority_end = rest.find(['/', '?', '#']).unwrap_or(rest.len());
    let raw_authority = &rest[..authority_end];
    let authority = raw_authority.rsplit_once('@').map_or(raw_authority, |(_, host)| host);
    let path = rest[authority_end..].split(['?', '#']).next().unwrap_or_default();

    format!("{scheme}://{authority}{path}")
}

impl fmt::Debug for Configuration {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        f.debug_struct("Configuration")
            .field("rpc_url", &redact_rpc_url(&self.rpc_url))
            .field("local_rpc_url", &redact_rpc_url(&self.local_rpc_url))
            .field("etherscan_api_key", &redact_secret(&self.etherscan_api_key))
            .field("transpose_api_key", &redact_secret(&self.transpose_api_key))
            .field("openrouter_api_key", &redact_secret(&self.openrouter_api_key))
            .field("openrouter_model", &self.openrouter_model)
            .field("llm_base_url", &redact_endpoint(&self.llm_base_url))
            .field("llm_api_key", &redact_secret(&self.llm_api_key))
            .field("llm_model", &self.llm_model)
            .field("llm_response_format", &self.llm_response_format)
            .finish()
    }
}

/// Explicit command-line LLM overrides.
#[derive(Clone, Default)]
pub struct LlmCliOverrides {
    /// A custom OpenAI-compatible base URL.
    pub base_url: String,
    /// An API key for the resolved endpoint.
    pub api_key: String,
    /// The legacy OpenRouter-only API key override.
    pub openrouter_api_key: String,
    /// The model identifier.
    pub model: String,
    /// The requested structured-output format.
    pub response_format: Option<LlmResponseFormat>,
}

impl fmt::Debug for LlmCliOverrides {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        f.debug_struct("LlmCliOverrides")
            .field("base_url", &redact_endpoint(&self.base_url))
            .field("api_key", &redact_secret(&self.api_key))
            .field("openrouter_api_key", &redact_secret(&self.openrouter_api_key))
            .field("model", &self.model)
            .field("response_format", &self.response_format)
            .finish()
    }
}

/// LLM-related environment variables.
#[derive(Clone, Default)]
pub struct LlmEnvironment {
    /// The base URL from `HEIMDALL_LLM_BASE_URL`.
    pub base_url: Option<String>,
    /// The API key from `HEIMDALL_LLM_API_KEY`.
    pub api_key: Option<String>,
}

impl fmt::Debug for LlmEnvironment {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        f.debug_struct("LlmEnvironment")
            .field("base_url", &self.base_url.as_deref().map(redact_endpoint))
            .field("api_key", &self.api_key.as_deref().map(redact_secret))
            .finish()
    }
}

/// Fully resolved LLM settings ready for client construction.
#[derive(Clone)]
pub struct ResolvedLlmSettings {
    /// The base URL of the OpenAI-compatible API.
    pub base_url: String,
    /// The API key, or an empty string when unauthenticated.
    pub api_key: String,
    /// The model identifier.
    pub model: String,
    /// The requested structured-output format.
    pub response_format: LlmResponseFormat,
    /// Whether the built-in OpenRouter endpoint was selected.
    pub uses_openrouter_default: bool,
}

impl fmt::Debug for ResolvedLlmSettings {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        f.debug_struct("ResolvedLlmSettings")
            .field("base_url", &redact_endpoint(&self.base_url))
            .field("api_key", &redact_secret(&self.api_key))
            .field("model", &self.model)
            .field("response_format", &self.response_format)
            .field("uses_openrouter_default", &self.uses_openrouter_default)
            .finish()
    }
}

fn first_non_empty<'a>(values: &[&'a str]) -> &'a str {
    values.iter().copied().find(|value| !value.is_empty()).unwrap_or_default()
}

/// Resolve LLM settings with explicit CLI values taking precedence over environment variables,
/// which take precedence over stored configuration.
///
/// A custom endpoint never inherits OpenRouter-specific keys or models from configuration or
/// MESC; callers must supply a model for custom endpoints.
pub fn resolve_llm_settings(
    cli: LlmCliOverrides,
    environment: LlmEnvironment,
    config: &Configuration,
) -> ResolvedLlmSettings {
    let environment_base_url = environment.base_url.as_deref().unwrap_or_default();
    let custom_base_url = first_non_empty(&[
        cli.base_url.as_str(),
        environment_base_url,
        config.llm_base_url.as_str(),
    ])
    .to_string();
    let response_format = cli.response_format.or(config.llm_response_format).unwrap_or_default();

    if !custom_base_url.is_empty() {
        let environment_api_key = environment.api_key.as_deref().unwrap_or_default();
        let api_key = first_non_empty(&[
            cli.api_key.as_str(),
            environment_api_key,
            config.llm_api_key.as_str(),
        ])
        .to_string();
        let model = first_non_empty(&[cli.model.as_str(), config.llm_model.as_str()]).to_string();

        return ResolvedLlmSettings {
            base_url: custom_base_url,
            api_key,
            model,
            response_format,
            uses_openrouter_default: false,
        };
    }

    let environment_api_key = environment.api_key.as_deref().unwrap_or_default();
    let api_key = first_non_empty(&[
        cli.api_key.as_str(),
        cli.openrouter_api_key.as_str(),
        environment_api_key,
        config.llm_api_key.as_str(),
        config.openrouter_api_key.as_str(),
    ])
    .to_string();
    let configured_model = first_non_empty(&[
        cli.model.as_str(),
        config.llm_model.as_str(),
        config.openrouter_model.as_str(),
    ]);
    let model = if configured_model.is_empty() {
        DEFAULT_MODEL.to_string()
    } else {
        configured_model.to_string()
    };

    ResolvedLlmSettings {
        base_url: OPENROUTER_API_BASE.to_string(),
        api_key,
        model,
        response_format,
        uses_openrouter_default: true,
    }
}

#[allow(deprecated)]
impl Configuration {
    /// Returns the current configuration.
    pub fn load() -> Result<Self, Error> {
        let mut home = home_dir().ok_or_else(|| {
            Error::Generic(
                "failed to get home directory. does your os support `std::env::home_dir()`?"
                    .to_string(),
            )
        })?;
        home.push(".bifrost");
        home.push("config.toml");

        // if the config file doesn't exist, create it
        if !home.exists() {
            let config = Configuration::default();
            config.save()?;
        }

        // read the config file
        let contents = read_file(
            home.to_str()
                .ok_or_else(|| Error::Generic("failed to convert path to string".to_string()))?,
        )
        .map_err(|e| Error::Generic(format!("failed to read config file: {e}")))?;

        // parse the config file
        let mut config: Configuration = toml::from_str(&contents)
            .map_err(|e| Error::ParseError(format!("failed to parse config file: {e}")))?;

        // load mesc config if enabled
        if !mesc::is_mesc_enabled() {
            return Ok(config);
        }

        if let Some(endpoint) = mesc::get_default_endpoint(Some("heimdall"))
            .map_err(|e| Error::Generic(format!("MESC error: {e}")))?
        {
            debug!("overriding rpc_url with mesc endpoint");
            config.rpc_url = endpoint.url;
        }
        if let Some(key) = mesc::metadata::get_api_key("etherscan", Some("heimdall"))
            .map_err(|e| Error::Generic(format!("MESC error: {e}")))?
        {
            debug!("overriding etherscan_api_key with mesc key");
            config.etherscan_api_key = key;
        }
        if let Some(key) = mesc::metadata::get_api_key("transpose", Some("heimdall"))
            .map_err(|e| Error::Generic(format!("MESC error: {e}")))?
        {
            debug!("overriding transpose_api_key with mesc key");
            config.transpose_api_key = key;
        }
        if let Some(key) = mesc::metadata::get_api_key("openrouter", Some("heimdall"))
            .map_err(|e| Error::Generic(format!("MESC error: {e}")))?
        {
            debug!("overriding openrouter_api_key with mesc key");
            config.openrouter_api_key = key;
        }

        Ok(config)
    }

    /// Saves the current configuration to disk.
    pub fn save(&self) -> Result<(), Error> {
        let mut home = home_dir().ok_or_else(|| {
            Error::Generic(
                "failed to get home directory. does your os support `std::env::home_dir()`?"
                    .to_string(),
            )
        })?;
        home.push(".bifrost");
        home.push("config.toml");

        write_file(
            home.to_str()
                .ok_or_else(|| Error::Generic("failed to convert path to string".to_string()))?,
            &toml::to_string(&self)
                .map_err(|e| Error::ParseError(format!("failed to serialize config: {e}")))?,
        )
        .map_err(|e| Error::Generic(format!("failed to write config file: {e}")))?;

        Ok(())
    }

    /// Deletes the configuration file at `$HOME/.bifrost/config.toml`.
    pub fn delete() -> Result<(), Error> {
        let mut home = home_dir().ok_or_else(|| {
            Error::Generic(
                "failed to get home directory. does your os support `std::env::home_dir()`?"
                    .to_string(),
            )
        })?;
        home.push(".bifrost");
        home.push("config.toml");

        delete_path(
            home.to_str()
                .ok_or_else(|| Error::Generic("failed to convert path to string".to_string()))?,
        );

        Ok(())
    }

    /// Update a single key/value pair in the configuration.
    pub fn update(&mut self, key: &str, value: &str) -> Result<(), Error> {
        // update the key in the struct and ensure it's the correct type
        match key {
            "rpc_url" => {
                self.rpc_url = value.to_string();
            }
            "local_rpc_url" => {
                self.local_rpc_url = value.to_string();
            }
            "etherscan_api_key" => {
                self.etherscan_api_key = value.to_string();
            }
            "transpose_api_key" => {
                self.transpose_api_key = value.to_string();
            }
            "openrouter_api_key" => {
                self.openrouter_api_key = value.to_string();
            }
            "openrouter_model" => {
                self.openrouter_model = value.to_string();
            }
            "llm_base_url" => {
                self.llm_base_url = value.to_string();
            }
            "llm_api_key" => {
                self.llm_api_key = value.to_string();
            }
            "llm_model" => {
                self.llm_model = value.to_string();
            }
            "llm_response_format" => {
                if value.is_empty() {
                    self.llm_response_format = None;
                } else {
                    self.llm_response_format = Some(value.parse().map_err(Error::Generic)?);
                }
            }
            _ => {
                return Err(Error::Generic(format!(
                    "invalid key: \'{key}\' is not a valid configuration key."
                )))
            }
        }

        // write the updated config to disk
        self.save()?;

        Ok(())
    }
}

/// The `config` command is used to display and edit the current configuration.
pub fn config(args: ConfigArgs) -> Result<(), Error> {
    if !args.key.is_empty() {
        if !args.value.is_empty() {
            // read the config file and update the key/value pair
            let mut config = Configuration::load()?;
            config.update(&args.key, &args.value)?;
            info!("updated configuration! Set '{}'.", &args.key);
        } else {
            // key is set, but no value is set
            error!("found key but no value to set. Please specify a value to set, use `heimdall config --help` for more information.");
        }
    } else {
        // no key is set, print the config file
        println!("{:#?}", Configuration::load()?);
        info!("use `heimdall config <KEY> <VALUE>` to set a key/value pair.");
    }

    Ok(())
}

/// Parse user input --rpc-url into a full url
pub fn parse_url_arg(url: &str) -> Result<String, String> {
    if mesc::is_mesc_enabled() {
        if let Ok(Some(endpoint)) = mesc::get_endpoint_by_query(url, Some("heimdall")) {
            return Ok(endpoint.url);
        }
    }
    Ok(url.to_string())
}

#[allow(deprecated)]
#[cfg(test)]
mod tests {
    use super::*;
    use serial_test::serial;

    // Test default configuration
    #[test]
    #[serial]
    fn test_default_configuration() {
        let config = Configuration::default();
        assert_eq!(config.rpc_url, "");
        assert_eq!(config.local_rpc_url, "http://localhost:8545");
        assert_eq!(config.etherscan_api_key, "");
        assert_eq!(config.transpose_api_key, "");
        assert_eq!(config.openrouter_api_key, "");
        assert_eq!(config.openrouter_model, "");
        assert_eq!(config.llm_base_url, "");
        assert_eq!(config.llm_api_key, "");
        assert_eq!(config.llm_model, "");
        assert_eq!(config.llm_response_format, None);
    }

    // Test loading configuration from a file
    #[test]
    #[serial]
    fn test_load_configuration() {
        // delete config file if it exists
        Configuration::delete().expect("failed to delete config file");
        let config = Configuration::load().expect("failed to load config file");

        assert_eq!(config.rpc_url, "");
        assert_eq!(config.local_rpc_url, "http://localhost:8545");
        assert_eq!(config.etherscan_api_key, "");
        assert_eq!(config.transpose_api_key, "");
        assert_eq!(config.openrouter_api_key, "");
        assert_eq!(config.openrouter_model, "");
        assert_eq!(config.llm_base_url, "");
        assert_eq!(config.llm_api_key, "");
        assert_eq!(config.llm_model, "");
        assert_eq!(config.llm_response_format, None);
    }

    // Test saving configuration to a file
    #[test]
    #[serial]
    fn test_save_configuration() {
        // delete config file if it exists
        Configuration::delete().expect("failed to delete config file");
        let mut config = Configuration::default();

        // update rpc_url
        config.update("rpc_url", "http://localhost:8545").expect("failed to update rpc_url");
        config
            .update("llm_base_url", "http://127.0.0.1:11434/v1")
            .expect("failed to update llm_base_url");
        config.update("llm_model", "local-model").expect("failed to update llm_model");
        config
            .update("llm_response_format", "json-object")
            .expect("failed to update llm_response_format");

        // save the config file
        config.save().expect("failed to save config file");

        // load the config file
        let loaded_config = Configuration::load().expect("failed to load config file");

        // ensure the config file was saved correctly
        assert_eq!(loaded_config.rpc_url, "http://localhost:8545");
        assert_eq!(loaded_config.local_rpc_url, "http://localhost:8545");
        assert_eq!(loaded_config.etherscan_api_key, "");
        assert_eq!(loaded_config.transpose_api_key, "");
        assert_eq!(loaded_config.openrouter_api_key, "");
        assert_eq!(loaded_config.openrouter_model, "");
        assert_eq!(loaded_config.llm_base_url, "http://127.0.0.1:11434/v1");
        assert_eq!(loaded_config.llm_model, "local-model");
        assert_eq!(loaded_config.llm_response_format, Some(LlmResponseFormat::JsonObject));
    }

    // Test deleting configuration file
    #[test]
    #[serial]
    fn test_delete_configuration() {
        // delete config file if it exists
        Configuration::delete().expect("failed to delete config file");
        let mut config = Configuration::load().expect("failed to load config file");

        // save some values to the config file
        config.update("rpc_url", "http://localhost:8545").expect("failed to update rpc_url");
        config
            .update("etherscan_api_key", "1234567890")
            .expect("failed to update etherscan_api_key");

        // delete config file if it exists
        Configuration::delete().expect("failed to delete config file");
        let config = Configuration::load().expect("failed to load config file");

        assert_eq!(config.rpc_url, "");
        assert_eq!(config.local_rpc_url, "http://localhost:8545");
        assert_eq!(config.etherscan_api_key, "");
        assert_eq!(config.transpose_api_key, "");
        assert_eq!(config.openrouter_api_key, "");
        assert_eq!(config.openrouter_model, "");
        assert_eq!(config.llm_base_url, "");
        assert_eq!(config.llm_api_key, "");
        assert_eq!(config.llm_model, "");
        assert_eq!(config.llm_response_format, None);
    }

    #[test]
    fn legacy_toml_without_new_fields_deserializes() {
        let contents = r#"
rpc_url = ""
local_rpc_url = "http://localhost:8545"
etherscan_api_key = ""
transpose_api_key = ""
openrouter_api_key = ""
openrouter_model = ""
"#;
        let config: Configuration = toml::from_str(contents).expect("legacy config must parse");
        assert_eq!(config.llm_base_url, "");
        assert_eq!(config.llm_api_key, "");
        assert_eq!(config.llm_model, "");
        assert_eq!(config.llm_response_format, None);
    }

    #[test]
    fn custom_endpoint_does_not_inherit_openrouter_settings() {
        let mut config = Configuration::default();
        config.openrouter_api_key = "openrouter-key".to_string();
        config.openrouter_model = "openrouter-model".to_string();
        config.llm_base_url = "http://127.0.0.1:1234/v1".to_string();
        config.llm_api_key = "local-key".to_string();
        config.llm_model = "local-model".to_string();

        let resolved =
            resolve_llm_settings(LlmCliOverrides::default(), LlmEnvironment::default(), &config);

        assert_eq!(resolved.base_url, "http://127.0.0.1:1234/v1");
        assert_eq!(resolved.api_key, "local-key");
        assert_eq!(resolved.model, "local-model");
        assert_eq!(resolved.response_format, LlmResponseFormat::Auto);
        assert!(!resolved.uses_openrouter_default);
    }

    #[test]
    fn custom_endpoint_requires_an_explicit_model() {
        let mut config = Configuration::default();
        config.llm_base_url = "http://127.0.0.1:1234/v1".to_string();
        config.openrouter_model = "openrouter-model".to_string();

        let resolved =
            resolve_llm_settings(LlmCliOverrides::default(), LlmEnvironment::default(), &config);

        assert_eq!(resolved.model, "");
        assert!(!resolved.uses_openrouter_default);
    }

    #[test]
    fn cli_overrides_environment_and_config() {
        let mut config = Configuration::default();
        config.llm_base_url = "http://config.example/v1".to_string();
        config.llm_api_key = "config-key".to_string();
        config.llm_model = "config-model".to_string();
        config.llm_response_format = Some(LlmResponseFormat::JsonSchema);

        let environment = LlmEnvironment {
            base_url: Some("http://env.example/v1".to_string()),
            api_key: Some("env-key".to_string()),
        };
        let cli = LlmCliOverrides {
            base_url: "http://cli.example/v1".to_string(),
            api_key: "cli-key".to_string(),
            openrouter_api_key: String::new(),
            model: "cli-model".to_string(),
            response_format: Some(LlmResponseFormat::JsonObject),
        };

        let resolved = resolve_llm_settings(cli, environment, &config);

        assert_eq!(resolved.base_url, "http://cli.example/v1");
        assert_eq!(resolved.api_key, "cli-key");
        assert_eq!(resolved.model, "cli-model");
        assert_eq!(resolved.response_format, LlmResponseFormat::JsonObject);
    }

    #[test]
    fn environment_overrides_stored_config() {
        let mut config = Configuration::default();
        config.llm_base_url = "http://config.example/v1".to_string();
        config.llm_api_key = "config-key".to_string();
        config.llm_model = "config-model".to_string();

        let environment = LlmEnvironment {
            base_url: Some("http://env.example/v1".to_string()),
            api_key: Some("env-key".to_string()),
        };

        let resolved = resolve_llm_settings(LlmCliOverrides::default(), environment, &config);

        assert_eq!(resolved.base_url, "http://env.example/v1");
        assert_eq!(resolved.api_key, "env-key");
        assert_eq!(resolved.model, "config-model");
    }

    #[test]
    fn openrouter_legacy_precedence_is_preserved() {
        let mut config = Configuration::default();
        config.openrouter_api_key = "config-openrouter-key".to_string();
        config.openrouter_model = "config-openrouter-model".to_string();

        let cli = LlmCliOverrides {
            openrouter_api_key: "cli-openrouter-key".to_string(),
            ..Default::default()
        };
        let environment =
            LlmEnvironment { api_key: Some("env-key".to_string()), ..Default::default() };

        let resolved = resolve_llm_settings(cli, environment, &config);
        assert!(resolved.uses_openrouter_default);
        assert_eq!(resolved.base_url, OPENROUTER_API_BASE);
        assert_eq!(resolved.api_key, "cli-openrouter-key");
        assert_eq!(resolved.model, "config-openrouter-model");

        let cli = LlmCliOverrides {
            api_key: "new-cli-key".to_string(),
            openrouter_api_key: "legacy-cli-key".to_string(),
            ..Default::default()
        };
        let resolved = resolve_llm_settings(cli, LlmEnvironment::default(), &config);
        assert_eq!(resolved.api_key, "new-cli-key");
    }

    #[test]
    fn openrouter_uses_default_model_when_none_is_configured() {
        let resolved = resolve_llm_settings(
            LlmCliOverrides::default(),
            LlmEnvironment::default(),
            &Configuration::default(),
        );

        assert!(resolved.uses_openrouter_default);
        assert_eq!(resolved.model, DEFAULT_MODEL);
    }

    #[test]
    fn response_format_precedence_is_respected() {
        let mut config = Configuration::default();
        config.llm_response_format = Some(LlmResponseFormat::JsonSchema);

        let resolved =
            resolve_llm_settings(LlmCliOverrides::default(), LlmEnvironment::default(), &config);
        assert_eq!(resolved.response_format, LlmResponseFormat::JsonSchema);

        let cli = LlmCliOverrides {
            response_format: Some(LlmResponseFormat::Text),
            ..Default::default()
        };
        let resolved = resolve_llm_settings(cli, LlmEnvironment::default(), &config);
        assert_eq!(resolved.response_format, LlmResponseFormat::Text);
    }

    #[test]
    fn debug_output_redacts_secrets_and_rpc_paths() {
        let mut config = Configuration::default();
        config.rpc_url =
            "https://user:password@rpc.example.com/v2/SUPER_SECRET?api_key=QUERY_SECRET"
                .to_string();
        config.local_rpc_url = "http://localhost:8545".to_string();
        config.etherscan_api_key = "etherscan-secret".to_string();
        config.transpose_api_key = "transpose-secret".to_string();
        config.openrouter_api_key = "openrouter-secret".to_string();
        config.llm_base_url = "http://127.0.0.1:11434/v1?token=ENDPOINT_SECRET".to_string();
        config.llm_api_key = "llm-secret".to_string();

        let debug = format!("{config:?}");

        for secret in [
            "SUPER_SECRET",
            "QUERY_SECRET",
            "password",
            "etherscan-secret",
            "transpose-secret",
            "openrouter-secret",
            "ENDPOINT_SECRET",
            "llm-secret",
        ] {
            assert!(!debug.contains(secret), "debug output leaked {secret}: {debug}");
        }
        assert!(debug.contains("http://localhost:8545"));
        assert!(debug.contains("http://127.0.0.1:11434/v1"));
        assert!(debug.contains("<redacted>"));
    }

    #[test]
    #[serial]
    fn update_rejects_invalid_response_format() {
        let mut config = Configuration::default();
        assert!(config.update("llm_response_format", "yaml").is_err());
        assert_eq!(config.llm_response_format, None);

        config.update("llm_response_format", "json-schema").expect("valid format");
        assert_eq!(config.llm_response_format, Some(LlmResponseFormat::JsonSchema));

        config.update("llm_response_format", "").expect("empty format clears value");
        assert_eq!(config.llm_response_format, None);
    }
}
