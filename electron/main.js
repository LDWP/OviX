/**
 * OviX Desktop - Main Electron Process
 * 
 * This is the main entry point for the Electron application.
 * It handles:
 * - Window management
 * - Python backend process management
 * - IPC communication with the renderer
 * - Auto-updater integration
 */

const { app, BrowserWindow, ipcMain, dialog } = require('electron');
const path = require('path');
const fs = require('fs');
const { spawn } = require('child_process');
const { performMigration } = require('./migration');

// Keep a global reference of the window object
let mainWindow = null;
let pythonProcess = null;

// Determine if we're in development mode
const isDev = process.env.NODE_ENV === 'development' || process.argv.includes('--dev');

// User data directory (separate from app files)
const userDataPath = app.getPath('userData');
const dataPath = path.join(userDataPath, 'data');
const logsPath = path.join(userDataPath, 'logs');
const configPath = path.join(userDataPath, 'config');

// Migration flag to avoid repeated migrations
const migrationFlagPath = path.join(userDataPath, '.migration_complete');

// Ensure user directories exist
function ensureUserDirectories() {
  [dataPath, logsPath, configPath].forEach(dir => {
    if (!fs.existsSync(dir)) {
      fs.mkdirSync(dir, { recursive: true });
    }
  });
}

// Perform data migration if needed
function checkAndPerformMigration() {
  // Skip migration in development mode
  if (isDev) {
    console.log('Development mode: skipping migration');
    return;
  }

  // Check if migration has already been done
  if (fs.existsSync(migrationFlagPath)) {
    console.log('Migration already completed, skipping');
    return;
  }

  console.log('Checking for existing data to migrate...');
  const projectRoot = path.join(__dirname, '..');
  
  // Check if there's data in the project directory
  const projectDataPath = path.join(projectRoot, 'data');
  const projectLogsPath = path.join(projectRoot, 'logs');
  const projectConfigPath = path.join(projectRoot, 'config');
  const projectEnvPath = path.join(projectRoot, '.env');
  
  const hasData = fs.existsSync(projectDataPath) || 
                 fs.existsSync(projectLogsPath) || 
                 fs.existsSync(projectConfigPath) || 
                 fs.existsSync(projectEnvPath);
  
  if (hasData) {
    console.log('Found existing data, performing migration...');
    const migrated = performMigration();
    if (migrated) {
      // Mark migration as complete
      fs.writeFileSync(migrationFlagPath, new Date().toISOString());
      console.log('Migration completed successfully');
    }
  } else {
    console.log('No existing data found, skipping migration');
    // Mark as complete even if no data to migrate
    fs.writeFileSync(migrationFlagPath, new Date().toISOString());
  }
}

// Create main browser window
function createWindow() {
  mainWindow = new BrowserWindow({
    width: 1400,
    height: 900,
    minWidth: 1200,
    minHeight: 700,
    webPreferences: {
      contextIsolation: true,
      nodeIntegration: false,
      preload: path.join(__dirname, 'preload.js'),
      webSecurity: true
    },
    icon: path.join(__dirname, '../resources/icon.png') // TODO: Add icon
  });

  // Load the app
  if (isDev) {
    // Development: load from Vite dev server
    mainWindow.loadURL('http://localhost:3001');
    mainWindow.webContents.openDevTools();
  } else {
    // Production: load from built files
    mainWindow.loadFile(path.join(__dirname, '../frontend/dist/index.html'));
  }

  mainWindow.on('closed', () => {
    mainWindow = null;
    stopPythonBackend();
  });
}

// Start Python backend
function startPythonBackend() {
  const projectRoot = path.join(__dirname, '..');
  
  // In development, use system Python
  // In production, use embedded Python
  const pythonCommand = isDev 
    ? 'python' 
    : path.join(process.resourcesPath, 'python', 'python.exe');
  
  const apiScript = path.join(projectRoot, 'backend', 'api', 'main.py');
  
  // Set environment variables for user data paths
  const env = {
    ...process.env,
    PROJECT_ROOT: projectRoot,
    OVIX_USER_DATA: userDataPath,
    OVIX_DATA_PATH: dataPath,
    OVIX_LOGS_PATH: logsPath,
    OVIX_CONFIG_PATH: configPath,
    PYWIKIBOT_DIR: projectRoot,
    PYWIKIBOT_NO_USER_CONFIG: '1',
    API_HOST: '127.0.0.1',
    API_PORT: '8001'
  };

  console.log(`Starting Python backend with: ${pythonCommand}`);
  console.log(`Working directory: ${projectRoot}`);
  
  pythonProcess = spawn(pythonCommand, ['-m', 'uvicorn', 'backend.api.main:app', '--host', '127.0.0.1', '--port', '8001', '--log-level', 'info'], {
    cwd: projectRoot,
    env: env,
    shell: true,
    detached: false
  });

  pythonProcess.stdout.on('data', (data) => {
    console.log(`Python stdout: ${data}`);
  });

  pythonProcess.stderr.on('data', (data) => {
    console.error(`Python stderr: ${data}`);
  });

  pythonProcess.on('close', (code) => {
    console.log(`Python process exited with code ${code}`);
  });
}

// Stop Python backend
function stopPythonBackend() {
  if (pythonProcess) {
    console.log('Stopping Python backend with PID:', pythonProcess.pid);
    try {
      // On Windows, use taskkill to force terminate the process
      if (process.platform === 'win32') {
        const { spawn } = require('child_process');
        const killProcess = spawn('taskkill', ['/F', '/PID', pythonProcess.pid], { 
          detached: true,
          stdio: 'ignore'
        });
        killProcess.unref();
        console.log('Taskkill command sent');
      } else {
        // On Unix/Mac, try graceful shutdown first
        pythonProcess.kill('SIGTERM');
        
        // Force kill after timeout
        setTimeout(() => {
          if (pythonProcess && !pythonProcess.killed) {
            console.log('Force killing Python backend...');
            pythonProcess.kill('SIGKILL');
          }
        }, 5000);
      }
    } catch (error) {
      console.error('Error stopping Python backend:', error);
    }
    pythonProcess = null;
  } else {
    console.log('No Python process to stop');
  }
}

// App event handlers
app.whenReady().then(() => {
  ensureUserDirectories();
  checkAndPerformMigration();
  createWindow();
  startPythonBackend();

  app.on('activate', () => {
    if (BrowserWindow.getAllWindows().length === 0) {
      createWindow();
    }
  });
});

app.on('window-all-closed', () => {
  console.log('All windows closed, stopping Python backend...');
  stopPythonBackend();
  
  if (process.platform !== 'darwin') {
    app.quit();
  }
});

app.on('before-quit', () => {
  console.log('App is about to quit, ensuring Python backend is stopped...');
  stopPythonBackend();
});

// IPC handlers
ipcMain.handle('get-app-version', () => {
  return app.getVersion();
});

ipcMain.handle('get-user-data-path', () => {
  return userDataPath;
});

ipcMain.handle('get-data-path', () => {
  return dataPath;
});

ipcMain.handle('get-logs-path', () => {
  return logsPath;
});

ipcMain.handle('get-config-path', () => {
  return configPath;
});

ipcMain.handle('restart-app', () => {
  app.relaunch();
  app.exit();
});

// Handle uncaught exceptions
process.on('uncaughtException', (error) => {
  console.error('Uncaught Exception:', error);
  // TODO: Log to file
});

process.on('unhandledRejection', (reason, promise) => {
  console.error('Unhandled Rejection at:', promise, 'reason:', reason);
  // TODO: Log to file
});
