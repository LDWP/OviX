/**
 * OviX Desktop - Data Migration Script
 * 
 * This script handles migration of existing data from the project directory
 * to the user data directory (%APPDATA%/OviX on Windows).
 * 
 * It ensures no data is lost during the migration process.
 */

const fs = require('fs');
const path = require('path');

const userDataPath = require('electron').app.getPath('userData');
const projectRoot = path.join(__dirname, '..');

// Data to migrate
const dataItems = [
  { source: 'data', target: 'data' },
  { source: 'logs', target: 'logs' },
  { source: 'config', target: 'config' },
  { source: '.env', target: '.env' }
];

function ensureDirectoryExists(dirPath) {
  if (!fs.existsSync(dirPath)) {
    fs.mkdirSync(dirPath, { recursive: true });
    console.log(`Created directory: ${dirPath}`);
  }
}

function copyFile(source, target) {
  try {
    if (fs.existsSync(source)) {
      ensureDirectoryExists(path.dirname(target));
      fs.copyFileSync(source, target);
      console.log(`Copied: ${source} -> ${target}`);
      return true;
    }
    return false;
  } catch (error) {
    console.error(`Error copying ${source}:`, error);
    return false;
  }
}

function copyDirectory(source, target) {
  try {
    if (!fs.existsSync(source)) {
      console.log(`Source directory does not exist: ${source}`);
      return false;
    }

    ensureDirectoryExists(target);
    
    const files = fs.readdirSync(source);
    let copied = 0;
    
    for (const file of files) {
      const sourcePath = path.join(source, file);
      const targetPath = path.join(target, file);
      
      if (fs.statSync(sourcePath).isDirectory()) {
        if (copyDirectory(sourcePath, targetPath)) {
          copied++;
        }
      } else {
        if (copyFile(sourcePath, targetPath)) {
          copied++;
        }
      }
    }
    
    return copied > 0;
  } catch (error) {
    console.error(`Error copying directory ${source}:`, error);
    return false;
  }
}

function performMigration() {
  console.log('Starting data migration...');
  console.log(`Project root: ${projectRoot}`);
  console.log(`User data path: ${userDataPath}`);
  
  let migratedCount = 0;
  
  for (const item of dataItems) {
    const sourcePath = path.join(projectRoot, item.source);
    const targetPath = path.join(userDataPath, item.target);
    
    console.log(`\nMigrating: ${item.source}`);
    
    if (fs.statSync(sourcePath).isDirectory()) {
      if (copyDirectory(sourcePath, targetPath)) {
        migratedCount++;
      }
    } else {
      if (copyFile(sourcePath, targetPath)) {
        migratedCount++;
      }
    }
  }
  
  console.log(`\nMigration complete. ${migratedCount}/${dataItems.length} items migrated.`);
  return migratedCount > 0;
}

// Export for use in main process
module.exports = {
  performMigration,
  copyFile,
  copyDirectory
};
