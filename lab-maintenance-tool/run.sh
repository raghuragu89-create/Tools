#!/bin/bash
# Lab Maintenance Tool - Touchless Automation
# Works on macOS and Linux
# Usage: chmod +x run.sh && ./run.sh

GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color
BOLD='\033[1m'

clear
echo ""
echo -e "${BLUE}${BOLD}  ======================================================"
echo "    Lab Maintenance Tool - Touchless Automation"
echo "    Rendering Lab (YJ) - 2026 Edition"
echo -e "  ======================================================${NC}"
echo ""

# Detect OS
if [[ "$OSTYPE" == "darwin"* ]]; then
    OS="macOS"
elif [[ "$OSTYPE" == "linux"* ]]; then
    OS="Linux"
else
    OS="Unknown"
fi
echo -e "  ${GREEN}[OK]${NC} OS: $OS"

# Check Python
PYTHON=""
if command -v python3 &>/dev/null; then
    PYTHON="python3"
elif command -v python &>/dev/null; then
    PYTHON="python"
fi

if [ -z "$PYTHON" ]; then
    echo -e "  ${RED}[ERROR]${NC} Python not found!"
    echo "  Install: brew install python3 (macOS) or sudo apt install python3 (Linux)"
    exit 1
fi
echo -e "  ${GREEN}[OK]${NC} Python: $($PYTHON --version)"
echo ""

# Install dependencies (first run)
if [ ! -f ".deps_installed" ]; then
    echo -e "  ${YELLOW}[SETUP]${NC} Installing dependencies (first run only)..."
    $PYTHON -m pip install -r requirements.txt --quiet 2>/dev/null
    if [ $? -eq 0 ]; then
        touch .deps_installed
        echo -e "  ${GREEN}[OK]${NC} Dependencies installed."
    else
        echo -e "  ${YELLOW}[WARN]${NC} Some deps failed. Trying without pip..."
    fi
    echo ""
fi

# Menu
show_menu() {
    echo -e "${BLUE}  ======================================================${NC}"
    echo -e "  ${BOLD}Choose an option:${NC}"
    echo -e "${BLUE}  ======================================================${NC}"
    echo ""
    echo "   1) Run Daily Health Report (now)"
    echo "   2) Run Weekly Restart (dry-run / safe)"
    echo "   3) Run Weekly Restart (LIVE - restarts devices)"
    echo "   4) Run IP Discovery only"
    echo "   5) Install as cron job (daily 09:00)"
    echo "   6) Start Scheduler (foreground)"
    echo "   7) Edit Configuration"
    echo "   8) View Last Report"
    echo "   9) Exit"
    echo ""
}

while true; do
    show_menu
    read -p "  Enter choice (1-9): " choice
    echo ""

    case $choice in
        1)
            echo -e "  ${GREEN}[RUNNING]${NC} Daily Health Report..."
            echo "  ======================================================"
            $PYTHON scheduler.py --run-now
            echo ""
            echo -e "  ${GREEN}[DONE]${NC} Report complete."
            echo ""
            read -p "  Press Enter to continue..."
            ;;
        2)
            echo -e "  ${GREEN}[RUNNING]${NC} Weekly Restart (DRY RUN)..."
            echo "  ======================================================"
            $PYTHON scheduler.py --restart-dry
            echo ""
            echo -e "  ${GREEN}[DONE]${NC} Dry run complete. No devices restarted."
            echo ""
            read -p "  Press Enter to continue..."
            ;;
        3)
            echo ""
            echo -e "  ${RED}!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!${NC}"
            echo -e "  ${RED}!! WARNING: This will RESTART all Android devices  !!${NC}"
            echo -e "  ${RED}!! Make sure no automation is running!             !!${NC}"
            echo -e "  ${RED}!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!${NC}"
            echo ""
            read -p "  Are you sure? (yes/no): " confirm
            if [ "$confirm" == "yes" ]; then
                $PYTHON scheduler.py --restart-now
            else
                echo "  Cancelled."
            fi
            echo ""
            read -p "  Press Enter to continue..."
            ;;
        4)
            echo -e "  ${GREEN}[RUNNING]${NC} IP Discovery..."
            echo "  ======================================================"
            $PYTHON collectors/ip_discovery.py --update
            echo ""
            read -p "  Press Enter to continue..."
            ;;
        5)
            echo -e "  ${GREEN}[INSTALLING]${NC} Cron job (daily at 09:00)..."
            SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
            CRON_CMD="0 9 * * * cd $SCRIPT_DIR && $PYTHON scheduler.py --run-now >> $SCRIPT_DIR/lab_report.log 2>&1"

            # Check if already installed
            if crontab -l 2>/dev/null | grep -q "lab-maintenance"; then
                echo -e "  ${YELLOW}[INFO]${NC} Cron job already exists."
            else
                (crontab -l 2>/dev/null; echo "$CRON_CMD # lab-maintenance") | crontab -
                echo -e "  ${GREEN}[OK]${NC} Installed: $CRON_CMD"
            fi
            echo ""
            echo "  Verify with: crontab -l"
            echo ""
            read -p "  Press Enter to continue..."
            ;;
        6)
            echo -e "  ${GREEN}[STARTING]${NC} Background scheduler..."
            echo "  (Press Ctrl+C to stop)"
            echo "  ======================================================"
            $PYTHON scheduler.py
            ;;
        7)
            if [[ "$OS" == "macOS" ]]; then
                open -e config.yaml 2>/dev/null || nano config.yaml
            else
                ${EDITOR:-nano} config.yaml
            fi
            ;;
        8)
            if [ -f "report_preview.html" ]; then
                if [[ "$OS" == "macOS" ]]; then
                    open report_preview.html
                else
                    xdg-open report_preview.html 2>/dev/null || echo "  Open report_preview.html in browser."
                fi
                echo -e "  ${GREEN}[OK]${NC} Opened report."
            else
                echo -e "  ${YELLOW}[INFO]${NC} No report yet. Run option 1 first."
            fi
            echo ""
            read -p "  Press Enter to continue..."
            ;;
        9)
            echo -e "  ${GREEN}Goodbye!${NC}"
            exit 0
            ;;
        *)
            echo -e "  ${RED}Invalid choice.${NC} Try again."
            ;;
    esac
    echo ""
done
