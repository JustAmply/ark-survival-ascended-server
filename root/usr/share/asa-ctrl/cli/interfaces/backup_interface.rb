module AsaCtrl
  module Cli
    class BackupInterface
      def initialize(opts)
        @opts = opts

        if @opts[:help]
          puts help_message
          exit 0
        end

        begin
          if @opts[:create]
            create_backup
          elsif @opts[:list]
            list_backups
          elsif @opts[:restore]
            restore_backup(@opts[:restore])
          elsif @opts[:cleanup]
            cleanup_backups
          else
            puts "Error: No action specified. Use --help for usage information."
            exit 1
          end
        rescue => e
          puts "Error: #{e.message}"
          exit 1
        end
      end

      private

      def create_backup
        puts "Creating server backup..."
        
        # Save world first if server is running
        if server_running?
          puts "Saving world before backup..."
          system("timeout 10 asa-ctrl rcon --exec 'saveworld' > /dev/null 2>&1")
          sleep 3 # Give save time to complete
        end
        
        timestamp = Time.now.strftime("%Y%m%d_%H%M%S")
        backup_name = @opts[:name] || "ark_backup_#{timestamp}"
        backup_name += ".tar.gz" unless backup_name.end_with?('.tar.gz')
        
        backup_dir = "/home/gameserver/backups"
        backup_path = "#{backup_dir}/#{backup_name}"
        
        # Create backup directory
        system("mkdir -p #{backup_dir}")
        
        # Create backup
        puts "Creating backup archive: #{backup_name}"
        puts "This may take several minutes..."
        
        server_files_path = "/home/gameserver/server-files"
        
        if system("tar -czf #{backup_path} -C #{server_files_path} --exclude='steamapps/downloading' --exclude='steamapps/temp' .")
          file_size = File.size(backup_path)
          size_mb = (file_size / (1024.0 * 1024.0)).round(2)
          
          puts "✅ Backup created successfully!"
          puts "   File: #{backup_path}"
          puts "   Size: #{size_mb} MB"
          
          # Update backup metadata
          update_backup_metadata(backup_name, timestamp, size_mb)
          
          # Cleanup old backups if requested
          cleanup_old_backups if @opts[:auto_cleanup]
        else
          puts "❌ Backup creation failed!"
          exit 1
        end
      end

      def list_backups
        backup_dir = "/home/gameserver/backups"
        metadata_file = "#{backup_dir}/.backup_metadata.json"
        
        unless Dir.exist?(backup_dir)
          puts "No backups found. Backup directory doesn't exist."
          return
        end
        
        backup_files = Dir.glob("#{backup_dir}/*.tar.gz").sort_by { |f| File.mtime(f) }.reverse
        
        if backup_files.empty?
          puts "No backups found."
          return
        end
        
        puts "📦 Available Backups:"
        puts
        
        # Load metadata if available
        metadata = {}
        if File.exist?(metadata_file)
          begin
            metadata = JSON.parse(File.read(metadata_file))
          rescue
            # Ignore metadata parsing errors
          end
        end
        
        backup_files.each_with_index do |file, index|
          basename = File.basename(file)
          file_size = File.size(file)
          size_mb = (file_size / (1024.0 * 1024.0)).round(2)
          mtime = File.mtime(file)
          
          puts "#{index + 1}. #{basename}"
          puts "   Created: #{mtime.strftime('%Y-%m-%d %H:%M:%S')}"
          puts "   Size: #{size_mb} MB"
          
          if metadata[basename]
            puts "   Description: #{metadata[basename]['description'] || 'No description'}"
          end
          
          puts
        end
      end

      def restore_backup(backup_name)
        backup_dir = "/home/gameserver/backups"
        
        # Find backup file
        backup_path = if backup_name.include?('/')
                       backup_name
                     else
                       backup_name += ".tar.gz" unless backup_name.end_with?('.tar.gz')
                       "#{backup_dir}/#{backup_name}"
                     end
        
        unless File.exist?(backup_path)
          # Try to find by partial name
          matches = Dir.glob("#{backup_dir}/*#{backup_name}*")
          if matches.length == 1
            backup_path = matches.first
          elsif matches.length > 1
            puts "Multiple backups match '#{backup_name}':"
            matches.each { |m| puts "  #{File.basename(m)}" }
            puts "Please be more specific."
            exit 1
          else
            puts "Backup file not found: #{backup_path}"
            exit 1
          end
        end
        
        puts "⚠️  WARNING: This will replace all current server data!"
        puts "Backup to restore: #{File.basename(backup_path)}"
        
        unless @opts[:force]
          print "Are you sure you want to continue? (yes/no): "
          response = STDIN.gets.chomp.downcase
          unless response == 'yes'
            puts "Restore cancelled."
            exit 0
          end
        end
        
        # Stop server if running
        if server_running?
          puts "Stopping server for restore..."
          # Note: This would need to be handled at the container level
          puts "Please stop the server container before restoring."
          exit 1
        end
        
        # Create restore point
        unless @opts[:no_backup]
          puts "Creating restore point..."
          restore_timestamp = Time.now.strftime("%Y%m%d_%H%M%S")
          restore_backup_name = "pre_restore_#{restore_timestamp}.tar.gz"
          system("tar -czf #{backup_dir}/#{restore_backup_name} -C /home/gameserver/server-files .")
        end
        
        # Restore backup
        puts "Restoring backup..."
        server_files_path = "/home/gameserver/server-files"
        
        if system("tar -xzf #{backup_path} -C #{server_files_path}")
          puts "✅ Backup restored successfully!"
          puts "You can now start the server."
        else
          puts "❌ Restore failed!"
          exit 1
        end
      end

      def cleanup_backups
        backup_dir = "/home/gameserver/backups"
        keep_count = @opts[:keep] || 5
        
        backup_files = Dir.glob("#{backup_dir}/*.tar.gz").sort_by { |f| File.mtime(f) }
        
        if backup_files.length <= keep_count
          puts "No cleanup needed. Found #{backup_files.length} backups, keeping #{keep_count}."
          return
        end
        
        to_delete = backup_files[0..-(keep_count + 1)]
        
        puts "Cleaning up old backups (keeping #{keep_count} most recent)..."
        
        to_delete.each do |file|
          puts "Deleting: #{File.basename(file)}"
          File.delete(file)
        end
        
        puts "✅ Cleanup complete. Deleted #{to_delete.length} old backups."
      end

      def cleanup_old_backups
        # Auto cleanup - keep last 10 backups by default
        backup_dir = "/home/gameserver/backups"
        backup_files = Dir.glob("#{backup_dir}/*.tar.gz").sort_by { |f| File.mtime(f) }
        
        if backup_files.length > 10
          to_delete = backup_files[0..-(11)]
          to_delete.each { |file| File.delete(file) }
          puts "Auto-cleanup: Removed #{to_delete.length} old backups."
        end
      end

      def update_backup_metadata(backup_name, timestamp, size_mb)
        backup_dir = "/home/gameserver/backups"
        metadata_file = "#{backup_dir}/.backup_metadata.json"
        
        metadata = {}
        if File.exist?(metadata_file)
          begin
            metadata = JSON.parse(File.read(metadata_file))
          rescue
            metadata = {}
          end
        end
        
        metadata[backup_name] = {
          'timestamp' => timestamp,
          'size_mb' => size_mb,
          'created_at' => Time.now.iso8601,
          'description' => @opts[:description] || ''
        }
        
        File.write(metadata_file, JSON.pretty_generate(metadata))
      end

      def server_running?
        system("pgrep -f 'ArkAscendedServer.exe\\|AsaApiLoader.exe' > /dev/null 2>&1")
      end

      def help_message
        <<~HELP
          Usage: asa-ctrl backup [options]

          Manage server backups for your ARK: Survival Ascended server.

          Actions:
            --create              Create a new backup
            --list                List all available backups
            --restore NAME        Restore from specified backup
            --cleanup             Clean up old backups

          Options:
            --name NAME           Name for the backup (default: timestamp)
            --description TEXT    Description for the backup
            --keep N              Number of backups to keep during cleanup (default: 5)
            --force               Skip confirmation prompts
            --no-backup           Don't create restore point before restoring
            --auto-cleanup        Automatically clean old backups after creation
            --help                Show this help message

          Examples:
            asa-ctrl backup --create                              # Create backup with timestamp
            asa-ctrl backup --create --name "before_mod_update"   # Create named backup
            asa-ctrl backup --list                                # List all backups
            asa-ctrl backup --restore "ark_backup_20231201"       # Restore specific backup
            asa-ctrl backup --cleanup --keep 3                   # Keep only 3 most recent backups

          Notes:
            - Backups are stored in /home/gameserver/backups/
            - The server world is automatically saved before backup creation
            - Restoring requires the server to be stopped
            - A restore point is created before restoring (unless --no-backup is used)
        HELP
      end
    end
  end
end