const CONFIG = {
  spreadsheetId: 'YOUR_SPREADSHEET_ID',
  sheetName: 'bot_server',
  triggerCellA1: 'AD1',
  botTriggerUrl: 'https://your-bot-host.example.com/trigger',
  sharedSecret: 'change-me',
};

function watchSeatalkTriggerCell() {
  const sheet = SpreadsheetApp.openById(CONFIG.spreadsheetId).getSheetByName(CONFIG.sheetName);
  if (!sheet) {
    throw new Error(`Sheet not found: ${CONFIG.sheetName}`);
  }

  const range = sheet.getRange(CONFIG.triggerCellA1);
  const currentValue = formatTriggerCellValue(range);
  const properties = PropertiesService.getScriptProperties();
  const propertyKey = buildPropertyKey();
  const previousValue = properties.getProperty(propertyKey);

  if (previousValue === null) {
    properties.setProperty(propertyKey, currentValue);
    Logger.log(`Baseline stored for ${CONFIG.sheetName}!${CONFIG.triggerCellA1}: ${currentValue}`);
    return;
  }

  if (currentValue === previousValue) {
    Logger.log(`No change in ${CONFIG.sheetName}!${CONFIG.triggerCellA1}: ${currentValue}`);
    return;
  }

  const payload = {
    trigger: 'apps_script_cell_change',
    source: 'google_apps_script',
    trigger_cell: CONFIG.triggerCellA1,
    previous_value: previousValue,
    current_value: currentValue,
    spreadsheet_id: CONFIG.spreadsheetId,
    tab_name: CONFIG.sheetName,
    fired_at: new Date().toISOString(),
    shared_secret: CONFIG.sharedSecret,
  };

  const response = UrlFetchApp.fetch(CONFIG.botTriggerUrl, {
    method: 'post',
    contentType: 'application/json',
    payload: JSON.stringify(payload),
    muteHttpExceptions: true,
  });

  const statusCode = response.getResponseCode();
  const responseBody = response.getContentText();
  if (statusCode < 200 || statusCode >= 300) {
    throw new Error(`Bot trigger failed with HTTP ${statusCode}: ${responseBody}`);
  }

  properties.setProperty(propertyKey, currentValue);
  Logger.log(`Change detected. Triggered bot for ${CONFIG.sheetName}!${CONFIG.triggerCellA1}.`);
}

function installMinuteTrigger() {
  deleteExistingWatchTriggers();
  ScriptApp.newTrigger('watchSeatalkTriggerCell')
    .timeBased()
    .everyMinutes(1)
    .create();
}

function deleteExistingWatchTriggers() {
  const triggers = ScriptApp.getProjectTriggers();
  for (const trigger of triggers) {
    if (trigger.getHandlerFunction() === 'watchSeatalkTriggerCell') {
      ScriptApp.deleteTrigger(trigger);
    }
  }
}

function resetSeatalkBaseline() {
  const sheet = SpreadsheetApp.openById(CONFIG.spreadsheetId).getSheetByName(CONFIG.sheetName);
  if (!sheet) {
    throw new Error(`Sheet not found: ${CONFIG.sheetName}`);
  }

  const currentValue = formatTriggerCellValue(sheet.getRange(CONFIG.triggerCellA1));
  PropertiesService.getScriptProperties().setProperty(buildPropertyKey(), currentValue);
  Logger.log(`Baseline reset for ${CONFIG.sheetName}!${CONFIG.triggerCellA1}: ${currentValue}`);
}

function buildPropertyKey() {
  return `seatalk_bot:${CONFIG.spreadsheetId}:${CONFIG.sheetName}:${CONFIG.triggerCellA1}`;
}

function formatTriggerCellValue(range) {
  const value = range.getValue();
  const displayValue = String(range.getDisplayValue() || '').trim();

  if (value === null || value === '') {
    return '';
  }

  if (Object.prototype.toString.call(value) === '[object Date]') {
    return Utilities.formatDate(value, Session.getScriptTimeZone(), 'h:mma MMM-dd');
  }

  if (typeof value === 'number' || typeof value === 'boolean') {
    if (displayValue) {
      return displayValue;
    }
    return String(value);
  }

  if (displayValue) {
    return displayValue;
  }

  return String(value).trim();
}
