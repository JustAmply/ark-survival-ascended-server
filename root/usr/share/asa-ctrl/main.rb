#!/usr/bin/ruby.ruby3.4
require 'json'
require 'slop'
require 'iniparse'
require 'socket'

if ENV['DEV'] == '1'
  require 'byebug'
end

require_relative './exit_codes.rb'
require_relative './errors/errors.rb'
require_relative './helpers/helpers.rb'
require_relative './mods/database.rb'
require_relative './rcon/rcon.rb'
require_relative './cli/utils.rb'
require_relative './cli/interfaces/cli_interface.rb'
require_relative './cli/interfaces/mods_interface.rb'
require_relative './cli/interfaces/rcon_interface.rb'
require_relative './cli/interfaces/status_interface.rb'
require_relative './cli/interfaces/backup_interface.rb'

main_args = Slop.parse(AsaCtrl::Cli.passed_command(ARGV)) do |args|
  args.on 'rcon', 'Interface for RCON command execution' do
    opts = Slop.parse(ARGV[1..-1]) do |opt|
      opt.string '--exec', 'An RCON command to execute'
      opt.bool AsaCtrl::Cli::HELP_ARGUMENT, AsaCtrl::Cli::HELP_DESCRIPTION
    end

    AsaCtrl::Cli::RconInterface.new(opts)
  end

  args.on 'status', 'Show detailed server status information' do
    opts = Slop.parse(ARGV[1..-1]) do |opt|
      opt.bool '--verbose', 'Show additional details'
      opt.bool AsaCtrl::Cli::HELP_ARGUMENT, AsaCtrl::Cli::HELP_DESCRIPTION
    end

    AsaCtrl::Cli::StatusInterface.new(opts)
  end

  args.on 'backup', 'Manage server backups' do
    opts = Slop.parse(ARGV[1..-1]) do |opt|
      opt.bool '--create', 'Create a new backup'
      opt.bool '--list', 'List all available backups'
      opt.string '--restore', 'Restore from specified backup'
      opt.bool '--cleanup', 'Clean up old backups'
      opt.string '--name', 'Name for the backup'
      opt.string '--description', 'Description for the backup'
      opt.integer '--keep', 'Number of backups to keep during cleanup'
      opt.bool '--force', 'Skip confirmation prompts'
      opt.bool '--no-backup', 'Don\'t create restore point before restoring'
      opt.bool '--auto-cleanup', 'Automatically clean old backups after creation'
      opt.bool AsaCtrl::Cli::HELP_ARGUMENT, AsaCtrl::Cli::HELP_DESCRIPTION
    end

    AsaCtrl::Cli::BackupInterface.new(opts)
  end

  args.on AsaCtrl::Cli::HELP_ARGUMENT, AsaCtrl::Cli::HELP_DESCRIPTION do
    # handled once slop exits
  end
end

AsaCtrl::Cli.print_usage
