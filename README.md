# aliyun-dev-server-cli

A CLI tool to create and relaunch development servers on Aliyun (Alibaba Cloud).

## Overview

This command-line interface tool helps developers quickly create and manage spot instance development servers on Aliyun. It automates the process of selecting appropriate instance types based on CPU and memory requirements and setting up storage with system disk image and data disk snapshots.

## Features

- **Spot Instance Management**: Automatically selects and creates spot instances based on your requirements
- **Data Persistence**: Uses snapshots to preserve data between server instances
- **Cost Optimization**: Leverages spot instances for significant cost savings
- **Easy Relaunch**: Quickly relaunch development servers with the same configuration and data

## Prerequisites

- Python 3.13+
- Aliyun account with appropriate permissions
- Access Key ID and Access Key Secret
- Pre-configured resources (images, snapshots, etc.)

## Installation

```bash
# Clone the repository
git clone <repository-url>
cd aliyun-dev-server-cli

# Install dependencies
pdm install
```

## Configuration

The tool can be configured through:
1. Environment variables
2. `.env` file
3. `config.toml` file
4. Command-line arguments

### Required Configuration

- `access_key_id`: Your Aliyun Access Key ID
- `access_key_secret`: Your Aliyun Access Key Secret
- `region_id`: Aliyun region (default: cn-hangzhou)

### Configuration File Example

Create a `config.toml` file with the following structure:

```toml
access_key_id = "your-access-key-id"
access_key_secret = "your-access-key-secret"
region_id = "cn-hangzhou"

[spot_instance_creation.dev_server]
image_name_pattern = "*your-image-keyword*"
cpu_count_range = [16, 32]
memory_size_range = [16.0, 32.0]
resource_group_name = "dev-resource-group"
instance_identifier = "dev-server"
dev_data_snapshot_identifier = "dev-data"
```

## Usage

```bash
# Create or relaunch a development server
python -m aliyun_dev_server_cli

# The tool will:
# 1. Find suitable instance types based on your CPU/memory requirements
# 2. Display available options with pricing information
# 3. Prompt you to select an instance type
# 4. Create the instance with proper networking and storage configuration
```

## How It Works

1. **Instance Selection**: The tool queries available instance types that match your CPU and memory requirements
2. **Price Comparison**: It compares spot prices across different zones and instance types
3. **Resource Setup**: Automatically configures VPC, VSwitch, and Security Groups
4. **Storage Configuration**: Attaches data disks from snapshots for data persistence
5. **Instance Creation**: Creates the spot instance with all configurations

## Contributing

Contributions are welcome! Please feel free to submit a Pull Request.

## License

This project is licensed under the MIT License - see the LICENSE file for details.
