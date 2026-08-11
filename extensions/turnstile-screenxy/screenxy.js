(() => {
  window.__lunesScreenXYPatchVersion = "1.1.0";
  const descriptorX = Object.getOwnPropertyDescriptor(
    MouseEvent.prototype,
    "clientX",
  );
  const descriptorY = Object.getOwnPropertyDescriptor(
    MouseEvent.prototype,
    "clientY",
  );
  if (!descriptorX?.get || !descriptorY?.get) return;

  const random = new Uint32Array(2);
  crypto.getRandomValues(random);
  const offsetX = 80 + (random[0] % 161);
  const offsetY = 80 + (random[1] % 121);

  Object.defineProperties(MouseEvent.prototype, {
    screenX: {
      configurable: true,
      get() {
        return offsetX + descriptorX.get.call(this);
      },
    },
    screenY: {
      configurable: true,
      get() {
        return offsetY + descriptorY.get.call(this);
      },
    },
  });
})();
