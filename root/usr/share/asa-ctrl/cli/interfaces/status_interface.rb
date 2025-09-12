module AsaCtrl
  module Cli
    class StatusInterface
      def initialize(opts)
        @opts = opts

        if @opts[:help]
          puts help_message
          exit 0
        end

        begin
          check_status
        rescue => e
          puts "Error: #{e.message}"
          exit 1
        end
      end

      private

      def check_status
        puts "\n=== ARK: Survival Ascended Server Status ==="
        puts

        # Check if server process is running
        server_running = check_server_process
        
        # Get basic server information
        if server_running
          puts "🟢 Server Status: RUNNING"
          show_server_details
          show_performance_info
          show_player_info
          show_recent_logs
        else
          puts "🔴 Server Status: STOPPED"
          puts
          puts "To start the server, run: docker compose up -d"
        end
      end

      def check_server_process
        # Check if the main ARK server process is running
        system("pgrep -f 'ArkAscendedServer.exe\\|AsaApiLoader.exe' > /dev/null 2>&1")
      end

      def show_server_details
        puts
        puts "📋 Server Details:"
        
        # Try to get server info from config
        begin
          config_path = "/home/gameserver/server-files/ShooterGame/Saved/Config/WindowsServer/GameUserSettings.ini"
          
          if File.exist?(config_path)
            config = IniParse.parse(File.read(config_path))
            
            session_name = config['ServerSettings']['SessionName'] rescue 'Unknown'
            max_players = config['ServerSettings']['MaxPlayers'] rescue 'Unknown'
            rcon_port = config['ServerSettings']['RCONPort'] rescue 'Unknown'
            
            puts "   Server Name: #{session_name}"
            puts "   Max Players: #{max_players}"
            puts "   RCON Port: #{rcon_port}"
          else
            puts "   Configuration not found (server may still be initializing)"
          end
        rescue => e
          puts "   Could not read server configuration: #{e.message}"
        end
      end

      def show_performance_info
        puts
        puts "⚡ Performance Info:"
        
        begin
          # Get memory usage
          memory_info = `ps -o pid,rss,vsz,comm -C ArkAscendedServer.exe 2>/dev/null | tail -n +2`
          if memory_info.empty?
            memory_info = `ps -o pid,rss,vsz,comm -C AsaApiLoader.exe 2>/dev/null | tail -n +2`
          end
          
          if !memory_info.empty?
            lines = memory_info.strip.split("\n")
            total_rss = 0
            lines.each do |line|
              parts = line.strip.split
              total_rss += parts[1].to_i if parts[1]
            end
            
            memory_mb = (total_rss / 1024.0).round(1)
            memory_gb = (memory_mb / 1024.0).round(2)
            
            puts "   Memory Usage: #{memory_mb} MB (#{memory_gb} GB)"
          else
            puts "   Memory Usage: Could not determine"
          end
          
          # Get uptime
          uptime_info = `ps -o etime -C ArkAscendedServer.exe 2>/dev/null | tail -n +2 | head -1`
          if uptime_info.empty?
            uptime_info = `ps -o etime -C AsaApiLoader.exe 2>/dev/null | tail -n +2 | head -1`
          end
          
          if !uptime_info.empty?
            puts "   Uptime: #{uptime_info.strip}"
          else
            puts "   Uptime: Could not determine"
          end
          
        rescue => e
          puts "   Performance info unavailable: #{e.message}"
        end
      end

      def show_player_info
        puts
        puts "👥 Player Information:"
        
        begin
          # Try to get player count via RCON
          if rcon_available?
            players_output = `timeout 5 asa-ctrl rcon --exec 'listplayers' 2>/dev/null`
            if $?.success? && !players_output.empty?
              # Parse player count from output
              player_lines = players_output.split("\n").select { |line| line.include?('.') && line.include?(',') }
              player_count = player_lines.length
              
              puts "   Current Players: #{player_count}"
              
              if player_count > 0 && @opts[:verbose]
                puts "   Player List:"
                player_lines.each do |line|
                  # Extract player name from the line (format varies)
                  if line =~ /.*,\s*(.+)$/
                    player_name = $1.strip
                    puts "     - #{player_name}"
                  end
                end
              end
            else
              puts "   Current Players: Unable to fetch (RCON unavailable)"
            end
          else
            puts "   Current Players: Unable to fetch (RCON not configured)"
          end
        rescue => e
          puts "   Player info unavailable: #{e.message}"
        end
      end

      def show_recent_logs
        puts
        puts "📝 Recent Activity (last 5 log lines):"
        puts
        
        begin
          log_output = `tail -5 /proc/1/fd/1 2>/dev/null`.strip
          if log_output.empty?
            puts "   No recent log entries available"
          else
            log_output.split("\n").each do |line|
              puts "   #{line}"
            end
          end
        rescue => e
          puts "   Log info unavailable: #{e.message}"
        end
        
        puts
        puts "For full logs, run: docker logs -f asa-server-1"
      end

      def rcon_available?
        config_path = "/home/gameserver/server-files/ShooterGame/Saved/Config/WindowsServer/GameUserSettings.ini"
        return false unless File.exist?(config_path)
        
        begin
          config = IniParse.parse(File.read(config_path))
          rcon_enabled = config['ServerSettings']['RCONEnabled'] rescue false
          admin_password = config['ServerSettings']['ServerAdminPassword'] rescue nil
          
          return rcon_enabled.to_s.downcase == 'true' && !admin_password.nil? && !admin_password.empty?
        rescue
          return false
        end
      end

      def help_message
        <<~HELP
          Usage: asa-ctrl status [options]

          Show detailed server status information including:
          - Server running state
          - Configuration details
          - Performance metrics
          - Current player count
          - Recent log activity

          Options:
            --verbose    Show additional details (like player names)
            --help       Show this help message

          Examples:
            asa-ctrl status           # Basic status information
            asa-ctrl status --verbose # Detailed status with player list
        HELP
      end
    end
  end
end