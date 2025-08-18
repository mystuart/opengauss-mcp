#!/bin/bash

# GaussDB-enabled Docker entrypoint script
# This script extends the base entrypoint with GaussDB-specific configuration and validation

set -e

# Color codes for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Logging functions
log_info() {
    echo -e "${BLUE}[INFO]${NC} $1" >&2
}

log_warn() {
    echo -e "${YELLOW}[WARN]${NC} $1" >&2
}

log_error() {
    echo -e "${RED}[ERROR]${NC} $1" >&2
}

log_success() {
    echo -e "${GREEN}[SUCCESS]${NC} $1" >&2
}

# Function to validate GaussDB configuration
validate_gaussdb_config() {
    log_info "Validating GaussDB configuration..."
    
    # Check if configuration file exists
    if [[ -n "$GAUSSDB_CONFIG_PATH" && -f "$GAUSSDB_CONFIG_PATH" ]]; then
        log_success "GaussDB configuration file found: $GAUSSDB_CONFIG_PATH"
    elif [[ -f "/app/config/gaussdb_compatibility.yaml" ]]; then
        export GAUSSDB_CONFIG_PATH="/app/config/gaussdb_compatibility.yaml"
        log_info "Using default GaussDB configuration: $GAUSSDB_CONFIG_PATH"
    else
        log_warn "No GaussDB configuration file found. Using built-in defaults."
    fi
    
    # Validate compatibility mode
    case "$GAUSSDB_COMPATIBILITY_MODE" in
        auto|force|disabled)
            log_info "GaussDB compatibility mode: $GAUSSDB_COMPATIBILITY_MODE"
            ;;
        *)
            log_warn "Invalid GAUSSDB_COMPATIBILITY_MODE: $GAUSSDB_COMPATIBILITY_MODE. Using 'auto'."
            export GAUSSDB_COMPATIBILITY_MODE=auto
            ;;
    esac
    
    # Validate benchmark configuration
    if [[ "$BENCHMARK_ENABLED" == "true" ]]; then
        log_info "Benchmark testing is enabled"
        
        # Check sysbench availability
        if command -v sysbench >/dev/null 2>&1; then
            SYSBENCH_VERSION=$(sysbench --version 2>/dev/null | head -n1 || echo "unknown")
            log_success "Sysbench available: $SYSBENCH_VERSION"
            export SYSBENCH_PATH=$(which sysbench)
        else
            log_warn "Sysbench not found. Benchmark testing may be limited."
        fi
        
        # Check TPC-C/HammerDB availability
        if command -v hammerdbcli >/dev/null 2>&1; then
            log_success "HammerDB CLI available for TPC-C testing"
            export TPCC_PATH=$(which hammerdbcli)
        else
            log_warn "HammerDB CLI not found. TPC-C testing will not be available."
        fi
        
        # Create benchmark results directory
        if [[ -n "$BENCHMARK_RESULTS_DIR" ]]; then
            mkdir -p "$BENCHMARK_RESULTS_DIR"
            log_info "Benchmark results directory: $BENCHMARK_RESULTS_DIR"
        fi
    else
        log_info "Benchmark testing is disabled"
    fi
}

# Function to replace localhost in a string with the Docker host
replace_localhost() {
    local input_str="$1"
    local docker_host=""

    # Try to determine Docker host address
    if ping -c 1 -w 1 host.docker.internal >/dev/null 2>&1; then
        docker_host="host.docker.internal"
        log_info "Docker Desktop detected: Using host.docker.internal for localhost"
    elif ping -c 1 -w 1 172.17.0.1 >/dev/null 2>&1; then
        docker_host="172.17.0.1"
        log_info "Docker on Linux detected: Using 172.17.0.1 for localhost"
    else
        log_warn "Cannot determine Docker host IP. Using original address."
        return 1
    fi

    # Replace localhost with Docker host
    if [[ -n "$docker_host" ]]; then
        local new_str="${input_str/localhost/$docker_host}"
        log_info "Remapping: $input_str --> $new_str"
        echo "$new_str"
        return 0
    fi

    # No replacement made
    echo "$input_str"
    return 1
}

# Function to detect database type from connection string
detect_database_from_uri() {
    local uri="$1"
    
    if [[ "$uri" == *"gaussdb"* ]] || [[ "$uri" == *"gauss"* ]]; then
        log_info "GaussDB detected in connection URI"
        export GAUSSDB_COMPATIBILITY_MODE=force
    elif [[ "$uri" == *"postgresql"* ]] || [[ "$uri" == *"postgres"* ]]; then
        log_info "PostgreSQL connection detected"
        # Keep current compatibility mode
    fi
}

# Function to set up environment variables
setup_environment() {
    log_info "Setting up GaussDB environment variables..."
    
    # Set default values if not provided
    export GAUSSDB_COMPATIBILITY_MODE=${GAUSSDB_COMPATIBILITY_MODE:-auto}
    export BENCHMARK_ENABLED=${BENCHMARK_ENABLED:-true}
    export DEBUG_LOGGING=${DEBUG_LOGGING:-false}
    export MAX_CONNECTIONS=${MAX_CONNECTIONS:-100}
    export CONNECTION_TIMEOUT=${CONNECTION_TIMEOUT:-30}
    export QUERY_CACHE_ENABLED=${QUERY_CACHE_ENABLED:-true}
    export BENCHMARK_RESULTS_DIR=${BENCHMARK_RESULTS_DIR:-/app/benchmark_results}
    
    # Create necessary directories
    mkdir -p /app/logs
    mkdir -p "$BENCHMARK_RESULTS_DIR"
    
    # Set Python path
    export PYTHONPATH="/app/src:$PYTHONPATH"
    
    log_info "Environment setup complete"
}

# Function to print configuration summary
print_config_summary() {
    log_info "=== GaussDB MCP Configuration Summary ==="
    echo "  Compatibility Mode: $GAUSSDB_COMPATIBILITY_MODE"
    echo "  Benchmark Enabled: $BENCHMARK_ENABLED"
    echo "  Debug Logging: $DEBUG_LOGGING"
    echo "  Max Connections: $MAX_CONNECTIONS"
    echo "  Connection Timeout: ${CONNECTION_TIMEOUT}s"
    echo "  Query Cache: $QUERY_CACHE_ENABLED"
    echo "  Config Path: ${GAUSSDB_CONFIG_PATH:-built-in}"
    echo "  Results Dir: $BENCHMARK_RESULTS_DIR"
    if [[ "$BENCHMARK_ENABLED" == "true" ]]; then
        echo "  Sysbench Path: ${SYSBENCH_PATH:-not found}"
        echo "  TPC-C Path: ${TPCC_PATH:-not found}"
    fi
    log_info "=========================================="
}

# Main execution starts here
log_info "Starting GaussDB-enabled Postgres MCP Pro..."

# Setup environment
setup_environment

# Validate configuration
validate_gaussdb_config

# Create a new array for the processed arguments
processed_args=()
processed_args+=("$1")
shift 1

# Process remaining command-line arguments for postgres:// or postgresql:// URLs that contain localhost
for arg in "$@"; do
    if [[ "$arg" == *"postgres"*"://"*"localhost"* ]]; then
        log_info "Found localhost in database connection: $arg"
        new_arg=$(replace_localhost "$arg")
        if [[ $? -eq 0 ]]; then
            processed_args+=("$new_arg")
        else
            processed_args+=("$arg")
        fi
        # Try to detect database type from URI
        detect_database_from_uri "$arg"
    else
        processed_args+=("$arg")
        # Try to detect database type from URI
        detect_database_from_uri "$arg"
    fi
done

# Check and replace localhost in DATABASE_URI if it exists
if [[ -n "$DATABASE_URI" && "$DATABASE_URI" == *"postgres"*"://"*"localhost"* ]]; then
    log_info "Found localhost in DATABASE_URI: $DATABASE_URI"
    new_uri=$(replace_localhost "$DATABASE_URI")
    if [[ $? -eq 0 ]]; then
        export DATABASE_URI="$new_uri"
    fi
    # Try to detect database type from URI
    detect_database_from_uri "$DATABASE_URI"
fi

# Check if SSE transport is specified and --sse-host is not already set
has_sse=false
has_sse_host=false

for arg in "${processed_args[@]}"; do
    if [[ "$arg" == "--transport" ]]; then
        # Check next argument for "sse"
        for next_arg in "${processed_args[@]}"; do
            if [[ "$next_arg" == "sse" ]]; then
                has_sse=true
                break
            fi
        done
    elif [[ "$arg" == "--transport=sse" ]]; then
        has_sse=true
    elif [[ "$arg" == "--sse-host"* ]]; then
        has_sse_host=true
    fi
done

# Add --sse-host if needed
if [[ "$has_sse" == true ]] && [[ "$has_sse_host" == false ]]; then
    log_info "SSE transport detected, adding --sse-host=0.0.0.0"
    processed_args+=("--sse-host=0.0.0.0")
fi

# Print configuration summary
print_config_summary

log_info "Executing command: ${processed_args[@]}"
log_info "=================="

# Execute the command with the processed arguments
"${processed_args[@]}"

# Capture exit code from the Python process
exit_code=$?

# If the Python process failed, print additional debug info
if [ $exit_code -ne 0 ]; then
    log_error "Command failed with exit code $exit_code"
    log_error "Command was: ${processed_args[@]}"
    
    # Print additional debug information
    if [[ "$DEBUG_LOGGING" == "true" ]]; then
        log_info "Debug information:"
        echo "  Environment variables:"
        env | grep -E "(GAUSSDB|DATABASE|BENCHMARK)" | sort
        echo "  Available tools:"
        command -v sysbench >/dev/null && echo "    sysbench: $(which sysbench)"
        command -v hammerdbcli >/dev/null && echo "    hammerdbcli: $(which hammerdbcli)"
    fi
fi

# Return the exit code from the Python process
exit $exit_code