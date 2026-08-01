/**
 * NPB data -> Google Sheets synchronizer for NotebookLM.
 * Paste this entire file into the Apps Script editor attached to a spreadsheet.
 */

const NPB_CONFIG = Object.freeze({
  baseUrl: 'https://raw.githubusercontent.com/wocchi09/npb-data/main/data/notebooklm/',
  triggerHourJst: 6,
  lockTimeoutMs: 30000,
  sources: [
    { file: 'games_latest.csv', sheet: '今日の試合' },
    { file: 'batting.csv', sheet: '野手成績' },
    { file: 'pitching.csv', sheet: '投手成績' },
    { file: 'teams.csv', sheet: '球団成績' },
    { file: 'matchups.csv', sheet: '対戦成績' },
    { file: 'roster.csv', sheet: '登録・抹消' },
    { file: 'form_players.csv', sheet: '好調・不調' },
    { file: 'glossary.csv', sheet: '指標説明' },
    { file: 'metadata.csv', sheet: 'データ情報' }
  ]
});

function onOpen() {
  SpreadsheetApp.getUi()
    .createMenu('NPBデータ')
    .addItem('初期設定', 'initialSetup')
    .addItem('今すぐ更新', 'updateNow')
    .addSeparator()
    .addItem('自動更新を設定', 'installDailyTrigger')
    .addItem('自動更新を解除', 'removeDailyTrigger')
    .addSeparator()
    .addItem('更新状況を確認', 'showUpdateStatus')
    .addToUi();
}

function initialSetup() {
  ensureControlSheets_();
  writeUsage_();
  updateAllData_({ interactive: true });
  installDailyTrigger();
  SpreadsheetApp.getUi().alert(
    '初期設定が完了しました。\nNotebookLMで、このスプレッドシートを情報源として追加してください。'
  );
}

function updateNow() {
  updateAllData_({ interactive: true });
}

function scheduledUpdate() {
  updateAllData_({ interactive: false });
}

function updateAllData_(options) {
  const interactive = Boolean(options && options.interactive);
  const lock = LockService.getDocumentLock();
  if (!lock.tryLock(NPB_CONFIG.lockTimeoutMs)) {
    const message = '別の更新処理が実行中のため、今回は更新しませんでした。';
    recordStatus_('スキップ', message, '');
    if (interactive) SpreadsheetApp.getUi().alert(message);
    return;
  }

  const started = new Date();
  try {
    ensureControlSheets_();
    recordStatus_('更新中', '公開CSVを取得しています。', started);

    // 全ファイルを先に取得・検証する。1つでも失敗したら既存データに触れない。
    const datasets = NPB_CONFIG.sources.map(function(source) {
      return { source: source, values: fetchCsv_(source.file) };
    });

    // 一時タブへの書き込みがすべて成功してから本番タブへ反映する。
    const tempSheets = prepareTemporarySheets_(datasets);
    try {
      datasets.forEach(function(dataset, index) {
        replaceSheetFromTemporary_(dataset.source.sheet, tempSheets[index]);
      });
    } finally {
      deleteTemporarySheets_(tempSheets);
    }

    const finished = new Date();
    PropertiesService.getDocumentProperties().setProperty('NPB_LAST_SUCCESS', finished.toISOString());
    recordStatus_('成功', datasets.length + 'ファイルを更新しました。', finished);
    formatDataSheets_();
    SpreadsheetApp.flush();
    if (interactive) SpreadsheetApp.getActive().toast('NPBデータを更新しました。', 'NPBデータ', 5);
  } catch (error) {
    const detail = error && error.stack ? error.stack : String(error);
    recordStatus_('失敗', String(error), new Date(), detail);
    if (interactive) SpreadsheetApp.getUi().alert('更新に失敗しました。\n「更新状況」タブを確認してください。\n\n' + String(error));
    throw error;
  } finally {
    lock.releaseLock();
  }
}

function fetchCsv_(fileName) {
  const url = NPB_CONFIG.baseUrl + fileName + '?ts=' + Date.now();
  let lastError = null;
  for (let attempt = 1; attempt <= 3; attempt++) {
    try {
      const response = UrlFetchApp.fetch(url, {
        muteHttpExceptions: true,
        followRedirects: true,
        headers: { Accept: 'text/csv,text/plain;q=0.9,*/*;q=0.1' }
      });
      const code = response.getResponseCode();
      if (code !== 200) throw new Error(fileName + ': HTTP ' + code);
      const text = response.getBlob().getDataAsString('UTF-8').replace(/^\uFEFF/, '');
      const values = Utilities.parseCsv(text);
      if (!values.length || !values[0].length || !values[0][0]) {
        throw new Error(fileName + ': CSVヘッダーがありません');
      }
      const width = values[0].length;
      values.forEach(function(row, rowIndex) {
        if (row.length !== width) throw new Error(fileName + ': ' + (rowIndex + 1) + '行目の列数が不正です');
      });
      return values;
    } catch (error) {
      lastError = error;
      if (attempt < 3) Utilities.sleep(1000 * attempt);
    }
  }
  throw new Error('取得失敗 ' + fileName + ': ' + String(lastError));
}

function prepareTemporarySheets_(datasets) {
  const spreadsheet = SpreadsheetApp.getActive();
  const created = [];
  try {
    datasets.forEach(function(dataset, index) {
      const name = '__NPB_TMP_' + index + '_' + Date.now();
      const sheet = spreadsheet.insertSheet(name);
      sheet.hideSheet();
      ensureSize_(sheet, dataset.values.length, dataset.values[0].length);
      sheet.getRange(1, 1, dataset.values.length, dataset.values[0].length).setValues(dataset.values);
      created.push(sheet);
    });
    SpreadsheetApp.flush();
    return created;
  } catch (error) {
    deleteTemporarySheets_(created);
    throw error;
  }
}

function replaceSheetFromTemporary_(targetName, tempSheet) {
  const spreadsheet = SpreadsheetApp.getActive();
  let target = spreadsheet.getSheetByName(targetName);
  if (!target) target = spreadsheet.insertSheet(targetName);
  const rows = tempSheet.getLastRow();
  const columns = tempSheet.getLastColumn();
  const values = tempSheet.getRange(1, 1, rows, columns).getValues();
  ensureSize_(target, rows, columns);
  target.clear({ contentsOnly: true });
  target.getRange(1, 1, rows, columns).setValues(values);
  if (target.getMaxRows() > rows) {
    target.getRange(rows + 1, 1, target.getMaxRows() - rows, target.getMaxColumns()).clearContent();
  }
}

function deleteTemporarySheets_(sheets) {
  const spreadsheet = SpreadsheetApp.getActive();
  (sheets || []).forEach(function(sheet) {
    try {
      if (spreadsheet.getSheetByName(sheet.getName())) spreadsheet.deleteSheet(sheet);
    } catch (ignored) {
      // 次回実行時にcleanupTemporarySheets_が回収する。
    }
  });
}

function cleanupTemporarySheets_() {
  const spreadsheet = SpreadsheetApp.getActive();
  spreadsheet.getSheets().forEach(function(sheet) {
    if (sheet.getName().indexOf('__NPB_TMP_') === 0) spreadsheet.deleteSheet(sheet);
  });
}

function ensureControlSheets_() {
  const spreadsheet = SpreadsheetApp.getActive();
  ['使い方', '更新状況'].concat(NPB_CONFIG.sources.map(function(x) { return x.sheet; })).forEach(function(name) {
    if (!spreadsheet.getSheetByName(name)) spreadsheet.insertSheet(name);
  });
  cleanupTemporarySheets_();
}

function ensureSize_(sheet, rows, columns) {
  if (sheet.getMaxRows() < rows) sheet.insertRowsAfter(sheet.getMaxRows(), rows - sheet.getMaxRows());
  if (sheet.getMaxColumns() < columns) sheet.insertColumnsAfter(sheet.getMaxColumns(), columns - sheet.getMaxColumns());
}

function writeUsage_() {
  const sheet = SpreadsheetApp.getActive().getSheetByName('使い方');
  const values = [
    ['NPBデータ × NotebookLM', ''],
    ['使い方', 'このスプレッドシートはGitHubで毎日生成されるNPBデータを自動取得します。'],
    ['1', '「NPBデータ → 初期設定」を一度実行し、Googleのアクセス許可を承認します。'],
    ['2', 'NotebookLMを開き、このスプレッドシートを情報源として追加します。'],
    ['3', '以後は毎朝6時ごろ（日本時間）に自動更新します。必要なら「今すぐ更新」を使えます。'],
    ['注意', 'NotebookLM側のソース同期にはGoogle側の都合で時間差が生じる場合があります。'],
    ['注意', '取得できない値は空欄です。サンプル不足フラグが「はい」の値は慎重に解釈してください。'],
    ['公開元', 'https://github.com/wocchi09/npb-data']
  ];
  sheet.clear();
  ensureSize_(sheet, values.length, 2);
  sheet.getRange(1, 1, values.length, 2).setValues(values);
  sheet.getRange(1, 1, 1, 2).setFontWeight('bold').setBackground('#1a73e8').setFontColor('#ffffff');
  sheet.setColumnWidth(1, 120);
  sheet.setColumnWidth(2, 720);
  sheet.getDataRange().setWrap(true).setVerticalAlignment('top');
}

function recordStatus_(status, message, at, detail) {
  const spreadsheet = SpreadsheetApp.getActive();
  let sheet = spreadsheet.getSheetByName('更新状況');
  if (!sheet) sheet = spreadsheet.insertSheet('更新状況');
  if (sheet.getLastRow() === 0) {
    sheet.appendRow(['記録日時', '状態', '内容', '詳細']);
    sheet.getRange(1, 1, 1, 4).setFontWeight('bold').setBackground('#d9ead3');
    sheet.setFrozenRows(1);
  }
  const timestamp = at instanceof Date ? at : new Date();
  sheet.appendRow([Utilities.formatDate(timestamp, 'Asia/Tokyo', 'yyyy-MM-dd HH:mm:ss'), status, message || '', detail || '']);
  if (sheet.getLastRow() > 101) sheet.deleteRows(2, sheet.getLastRow() - 101);
  sheet.autoResizeColumns(1, 3);
  sheet.setColumnWidth(4, 500);
}

function formatDataSheets_() {
  NPB_CONFIG.sources.forEach(function(source) {
    const sheet = SpreadsheetApp.getActive().getSheetByName(source.sheet);
    if (!sheet || sheet.getLastRow() === 0) return;
    sheet.setFrozenRows(1);
    sheet.getRange(1, 1, 1, sheet.getLastColumn()).setFontWeight('bold').setBackground('#d9ead3');
    if (sheet.getFilter()) sheet.getFilter().remove();
    sheet.getDataRange().createFilter();
    sheet.autoResizeColumns(1, sheet.getLastColumn());
  });
}

function installDailyTrigger() {
  removeDailyTrigger_(false);
  ScriptApp.newTrigger('scheduledUpdate')
    .timeBased()
    .atHour(NPB_CONFIG.triggerHourJst)
    .everyDays(1)
    .inTimezone('Asia/Tokyo')
    .create();
  recordStatus_('設定', '毎日6時台（日本時間）の自動更新を設定しました。', new Date());
  SpreadsheetApp.getActive().toast('自動更新を設定しました。', 'NPBデータ', 5);
}

function removeDailyTrigger() {
  removeDailyTrigger_(true);
}

function removeDailyTrigger_(notify) {
  let removed = 0;
  ScriptApp.getProjectTriggers().forEach(function(trigger) {
    if (trigger.getHandlerFunction() === 'scheduledUpdate') {
      ScriptApp.deleteTrigger(trigger);
      removed++;
    }
  });
  if (notify) {
    recordStatus_('設定解除', '自動更新トリガーを' + removed + '件解除しました。', new Date());
    SpreadsheetApp.getActive().toast('自動更新を解除しました。', 'NPBデータ', 5);
  }
}

function showUpdateStatus() {
  ensureControlSheets_();
  const sheet = SpreadsheetApp.getActive().getSheetByName('更新状況');
  SpreadsheetApp.getActive().setActiveSheet(sheet);
}
