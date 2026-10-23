function buildPieRenderCapabilities(options) {
  return {
    ctx: options.getCtx(),
    rect: options.getRect(),
    subjects: options.getSubjects(),
    themeMode: options.getThemeMode(),
    dpr: options.getDpr(),
    selectedSubject: options.getSelectedSubject(),
    palette: options.getPalette(),
    cache: options.getCache(),
    shade: options.getShade(),
  }
}

module.exports = {
  buildPieRenderCapabilities,
}
