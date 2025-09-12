.PHONY: prepare build build-development build-beta load install setup start stop restart status logs backup clean help

GLOBAL_BUILD_DIR = /tmp/.kiwi-build-results
TARGET_DIR = $(GLOBAL_BUILD_DIR)/ark-survival-ascended-linux-container-image
COMPOSE_FILE = docker-compose.yml
CONTAINER_NAME = asa-server-1

# Color codes for output
GREEN = \033[0;32m
YELLOW = \033[1;33m
RED = \033[0;31m
NC = \033[0m # No Color

# Build targets (original functionality)
prepare:
	- sudo rm -rf $(TARGET_DIR)
	- mkdir -p $(GLOBAL_BUILD_DIR)

build: prepare
	- sudo kiwi-ng --profile stable --color-output --debug system build --target-dir $(TARGET_DIR) --description .
	- sudo xz --threads 8 -z $(TARGET_DIR)/*.tar

build-development: prepare
	- sudo kiwi-ng --profile development --color-output --debug system build --target-dir $(TARGET_DIR) --description .
	- sudo xz --threads 8 -z $(TARGET_DIR)/*.tar

build-beta: prepare
	- sudo kiwi-ng --profile beta --color-output --debug system build --target-dir $(TARGET_DIR) --description .
	- sudo xz --threads 8 -z $(TARGET_DIR)/*.tar

load:
	- sudo docker load -i $(TARGET_DIR)/*.xz

# Quality of Life targets for server management
install: setup

setup:
	@echo "$(GREEN)🚀 Starting ARK Server Setup...$(NC)"
	@if [ -x "./setup-wizard.sh" ]; then \
		./setup-wizard.sh; \
	else \
		echo "$(RED)❌ Setup wizard not found. Please ensure setup-wizard.sh exists and is executable.$(NC)"; \
		exit 1; \
	fi

start:
	@echo "$(GREEN)🟢 Starting ARK server...$(NC)"
	@docker compose -f $(COMPOSE_FILE) up -d
	@echo "$(YELLOW)⏳ Server is starting up. This may take 10-20 minutes for the first start.$(NC)"
	@echo "$(YELLOW)💡 Follow the logs with: make logs$(NC)"

stop:
	@echo "$(YELLOW)🔴 Stopping ARK server...$(NC)"
	@docker compose -f $(COMPOSE_FILE) stop

restart:
	@echo "$(YELLOW)🔄 Restarting ARK server...$(NC)"
	@if docker ps --format '{{.Names}}' | grep -q '^$(CONTAINER_NAME)$$'; then \
		echo "$(YELLOW)💾 Saving world before restart...$(NC)"; \
		docker exec $(CONTAINER_NAME) asa-ctrl rcon --exec 'saveworld' 2>/dev/null || echo "$(YELLOW)⚠️  RCON save failed (server might be starting)$(NC)"; \
		sleep 3; \
	fi
	@docker compose -f $(COMPOSE_FILE) restart
	@echo "$(GREEN)✅ Server restarted. Check status with: make status$(NC)"

status:
	@echo "$(GREEN)📊 ARK Server Status:$(NC)"
	@echo ""
	@if docker ps --format '{{.Names}}\t{{.Status}}' | grep -q '^$(CONTAINER_NAME)'; then \
		echo "$(GREEN)✅ Container Status: RUNNING$(NC)"; \
		docker exec $(CONTAINER_NAME) asa-ctrl status 2>/dev/null || echo "$(YELLOW)⚠️  Status command failed - server might be starting$(NC)"; \
	else \
		echo "$(RED)❌ Container Status: STOPPED$(NC)"; \
		echo "$(YELLOW)💡 Start the server with: make start$(NC)"; \
	fi

logs:
	@echo "$(GREEN)📋 Showing ARK server logs (Ctrl+C to exit):$(NC)"
	@docker logs -f $(CONTAINER_NAME)

backup:
	@echo "$(GREEN)💾 Creating server backup...$(NC)"
	@if docker ps --format '{{.Names}}' | grep -q '^$(CONTAINER_NAME)$$'; then \
		docker exec $(CONTAINER_NAME) asa-ctrl backup --create --auto-cleanup; \
	else \
		echo "$(RED)❌ Server is not running. Cannot create backup.$(NC)"; \
		exit 1; \
	fi

list-backups:
	@echo "$(GREEN)📦 Available backups:$(NC)"
	@docker exec $(CONTAINER_NAME) asa-ctrl backup --list

quick-backup:
	@echo "$(GREEN)💾 Creating quick backup...$(NC)"
	@if [ -z "$(name)" ]; then \
		echo "$(RED)❌ Please provide a backup name: make quick-backup name=my_backup$(NC)"; \
		exit 1; \
	fi
	@docker exec $(CONTAINER_NAME) asa-ctrl backup --create --name "$(name)"

restore-backup:
	@echo "$(YELLOW)🔄 Restoring backup...$(NC)"
	@if [ -z "$(name)" ]; then \
		echo "$(RED)❌ Please provide a backup name: make restore-backup name=backup_name$(NC)"; \
		exit 1; \
	fi
	@echo "$(RED)⚠️  WARNING: This will stop the server and replace all data!$(NC)"
	@read -p "Are you sure? [y/N] " -n 1 -r; \
	echo ""; \
	if [[ $$REPLY =~ ^[Yy]$$ ]]; then \
		make stop; \
		docker exec $(CONTAINER_NAME) asa-ctrl backup --restore "$(name)" --force; \
		echo "$(GREEN)✅ Backup restored. Start server with: make start$(NC)"; \
	else \
		echo "$(YELLOW)Backup restore cancelled.$(NC)"; \
	fi

update:
	@echo "$(GREEN)🔄 Updating container image...$(NC)"
	@docker pull mschnitzer/asa-linux-server:latest
	@echo "$(YELLOW)💡 Restart the server to use the new image: make restart$(NC)"

clean:
	@echo "$(YELLOW)🧹 Cleaning up...$(NC)"
	@docker compose -f $(COMPOSE_FILE) down
	@docker system prune -f
	@echo "$(GREEN)✅ Cleanup complete$(NC)"

rcon:
	@if [ -z "$(cmd)" ]; then \
		echo "$(RED)❌ Please provide an RCON command: make rcon cmd='saveworld'$(NC)"; \
		exit 1; \
	fi
	@echo "$(GREEN)🎮 Executing RCON command: $(cmd)$(NC)"
	@docker exec $(CONTAINER_NAME) asa-ctrl rcon --exec '$(cmd)'

players:
	@echo "$(GREEN)👥 Current players:$(NC)"
	@docker exec $(CONTAINER_NAME) asa-ctrl rcon --exec 'listplayers'

save:
	@echo "$(GREEN)💾 Saving world...$(NC)"
	@docker exec $(CONTAINER_NAME) asa-ctrl rcon --exec 'saveworld'

broadcast:
	@if [ -z "$(msg)" ]; then \
		echo "$(RED)❌ Please provide a message: make broadcast msg='Hello players!'$(NC)"; \
		exit 1; \
	fi
	@echo "$(GREEN)📢 Broadcasting message: $(msg)$(NC)"
	@docker exec $(CONTAINER_NAME) asa-ctrl rcon --exec 'broadcast $(msg)'

help:
	@echo "$(GREEN)ARK: Survival Ascended Server Management$(NC)"
	@echo ""
	@echo "$(YELLOW)Setup & Installation:$(NC)"
	@echo "  make setup              Run the interactive setup wizard"
	@echo "  make install            Alias for setup"
	@echo ""
	@echo "$(YELLOW)Server Management:$(NC)"
	@echo "  make start              Start the ARK server"
	@echo "  make stop               Stop the ARK server"
	@echo "  make restart            Restart the ARK server (with world save)"
	@echo "  make status             Show server status and performance info"
	@echo "  make logs               Show and follow server logs"
	@echo ""
	@echo "$(YELLOW)Backup Management:$(NC)"
	@echo "  make backup             Create automatic backup with cleanup"
	@echo "  make list-backups       List all available backups"
	@echo "  make quick-backup name=NAME    Create named backup"
	@echo "  make restore-backup name=NAME  Restore from backup"
	@echo ""
	@echo "$(YELLOW)Server Commands:$(NC)"
	@echo "  make rcon cmd='COMMAND' Execute RCON command"
	@echo "  make players            List current players"
	@echo "  make save               Save the world"
	@echo "  make broadcast msg='MSG' Broadcast message to players"
	@echo ""
	@echo "$(YELLOW)Maintenance:$(NC)"
	@echo "  make update             Update container image"
	@echo "  make clean              Stop server and clean up Docker resources"
	@echo ""
	@echo "$(YELLOW)Build (Advanced):$(NC)"
	@echo "  make build              Build stable container image"
	@echo "  make build-development  Build development container image"
	@echo "  make build-beta         Build beta container image"
	@echo ""
	@echo "$(GREEN)Examples:$(NC)"
	@echo "  make setup                                    # Initial setup"
	@echo "  make start && make logs                       # Start and monitor"
	@echo "  make quick-backup name=before_mod_update      # Named backup"
	@echo "  make rcon cmd='listplayers'                   # List players"
	@echo "  make broadcast msg='Server restart in 5 min' # Warn players"
