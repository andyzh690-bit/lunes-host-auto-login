(() => {
  window.__lunesScreenXYPatchVersion = "1.2.0";

  const randomInteger = (minimum, maximum) =>
    Math.floor(Math.random() * (maximum - minimum + 1)) + minimum;

  const screenX = randomInteger(800, 1200);
  const screenY = randomInteger(400, 600);

  Object.defineProperty(MouseEvent.prototype, "screenX", {
    configurable: true,
    value: screenX,
  });
  Object.defineProperty(MouseEvent.prototype, "screenY", {
    configurable: true,
    value: screenY,
  });
})();
