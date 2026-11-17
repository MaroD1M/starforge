/* starforge · 极简 glTF(.glb) 查看器：只认我们自己产的 glb
 * 支持：POSITION / NORMAL / indices(float32 + uint32)，按 primitive 材质取基色
 * 交互：拖拽旋转、滚轮缩放、预设视角、自动旋转。失败时上层退回服务端 PNG。 */
(function () {
  const VS = `
    attribute vec3 aPos; attribute vec3 aNrm;
    uniform mat4 uMvp; uniform mat3 uNormal;
    varying vec3 vN;
    void main(){ vN = uNormal * aNrm; gl_Position = uMvp * vec4(aPos, 1.0); }`;
  const FS = `
    precision mediump float;
    varying vec3 vN; uniform vec3 uColor; uniform vec3 uLight;
    void main(){
      float d = max(dot(normalize(vN), normalize(uLight)), 0.0);
      vec3 c = uColor * (0.34 + 0.66 * d);
      gl_FragColor = vec4(c, 1.0);
    }`;

  function mat4Mul(a, b) {                       // column-major
    const o = new Float32Array(16);
    for (let c = 0; c < 4; c++) for (let r = 0; r < 4; r++) {
      let s = 0; for (let k = 0; k < 4; k++) s += a[k * 4 + r] * b[c * 4 + k];
      o[c * 4 + r] = s;
    }
    return o;
  }
  function perspective(fovy, aspect, near, far) {
    const f = 1 / Math.tan(fovy / 2), nf = 1 / (near - far);
    return new Float32Array([f / aspect,0,0,0, 0,f,0,0, 0,0,(far+near)*nf,-1, 0,0,2*far*near*nf,0]);
  }
  function lookAt(eye, target, up) {
    const z = norm(sub(eye, target)), x = norm(cross(up, z)), y = cross(z, x);
    return new Float32Array([x[0],y[0],z[0],0, x[1],y[1],z[1],0, x[2],y[2],z[2],0,
                             -dot(x,eye),-dot(y,eye),-dot(z,eye),1]);
  }
  const sub=(a,b)=>[a[0]-b[0],a[1]-b[1],a[2]-b[2]];
  const cross=(a,b)=>[a[1]*b[2]-a[2]*b[1],a[2]*b[0]-a[0]*b[2],a[0]*b[1]-a[1]*b[0]];
  const dot=(a,b)=>a[0]*b[0]+a[1]*b[1]+a[2]*b[2];
  const norm=a=>{const l=Math.hypot(a[0],a[1],a[2])||1;return [a[0]/l,a[1]/l,a[2]/l];};

  function parseGlb(buf) {
    const dv = new DataView(buf);
    if (dv.getUint32(0, true) !== 0x46546C67) throw new Error('不是 glb');
    let off = 12, json = null, bin = null;
    while (off < dv.byteLength) {
      const len = dv.getUint32(off, true), type = dv.getUint32(off + 4, true);
      const data = new Uint8Array(buf, off + 8, len); off += 8 + len;
      if (type === 0x4E4F534A) json = JSON.parse(new TextDecoder().decode(data));
      else if (type === 0x004E4942) bin = data;
    }
    if (!json || !bin) throw new Error('glb 缺少 chunk');
    return { json, bin };
  }

  function accArray(gltf, bin, index) {
    const acc = gltf.accessors[index], view = gltf.bufferViews[acc.bufferView];
    const start = (view.byteOffset || 0) + (acc.byteOffset || 0);
    const Ctor = acc.componentType === 5126 ? Float32Array
               : acc.componentType === 5125 ? Uint32Array
               : acc.componentType === 5123 ? Uint16Array : Uint8Array;
    const per = { SCALAR: 1, VEC2: 2, VEC3: 3, VEC4: 4 }[acc.type];
    return new Ctor(bin.buffer, bin.byteOffset + start, acc.count * per);
  }

  function mount(canvas) {
    let gl = canvas.getContext('webgl2', { antialias: true, alpha: false });
    let isGles2 = !!gl;
    if (!gl) gl = canvas.getContext('webgl', { antialias: true, alpha: false });
    if (!gl) throw new Error('浏览器不支持 WebGL');
    let uintIndex = isGles2;
    if (!isGles2) {
      uintIndex = !!gl.getExtension('OES_element_index_uint');
      if (!uintIndex) throw new Error('缺少 OES_element_index_uint（无法画高面数模型）');
    }
    const prog = (() => {
      const p = gl.createProgram();
      [[gl.VERTEX_SHADER, VS], [gl.FRAGMENT_SHADER, FS]].forEach(([t, src]) => {
        const s = gl.createShader(t); gl.shaderSource(s, src); gl.compileShader(s);
        if (!gl.getShaderParameter(s, gl.COMPILE_STATUS)) throw new Error(gl.getShaderInfoLog(s));
        gl.attachShader(p, s);
      });
      gl.linkProgram(p); if (!gl.getProgramParameter(p, gl.LINK_STATUS)) throw new Error('link 失败');
      return p;
    })();
    const loc = n => gl.getUniformLocation(prog, n);
    const U = { mvp: loc('uMvp'), normal: loc('uNormal'), color: loc('uColor'), light: loc('uLight') };

    let prims = [], radius = 3, alive = true;
    let yaw = 0.6, pitch = 0.35, dist = 1.0, spin = false, dirty = true;

    function upload(gltf, bin) {
      prims.forEach(p => { gl.deleteBuffer(p.pos); gl.deleteBuffer(p.nrm); gl.deleteBuffer(p.idx); });
      prims = [];
      const mats = gltf.materials || [];
      for (const mesh of gltf.meshes || []) {
        for (const pr of mesh.primitives) {
          const pos = accArray(gltf, bin, pr.attributes.POSITION);
          const nrm = pr.attributes.NORMAL != null ? accArray(gltf, bin, pr.attributes.NORMAL) : null;
          const idx = pr.indices != null ? accArray(gltf, bin, pr.indices) : null;
          const mat = mats[pr.material] || {};
          const c = (mat.pbrMetallicRoughness && mat.pbrMetallicRoughness.baseColorFactor) || [0.72, 0.72, 0.74, 1];
          const b = { pos: gl.createBuffer(), nrm: gl.createBuffer(), idx: gl.createBuffer(),
                      count: idx ? idx.length : pos.length / 3, color: c.slice(0, 3) };
          gl.bindBuffer(gl.ARRAY_BUFFER, b.pos); gl.bufferData(gl.ARRAY_BUFFER, pos, gl.STATIC_DRAW);
          gl.bindBuffer(gl.ARRAY_BUFFER, b.nrm);
          gl.bufferData(gl.ARRAY_BUFFER, nrm || new Float32Array(pos.length).fill(0).map((_, i) => (i % 3 === 1 ? 1 : 0)), gl.STATIC_DRAW);
          gl.bindBuffer(gl.ELEMENT_ARRAY_BUFFER, b.idx);
          gl.bufferData(gl.ELEMENT_ARRAY_BUFFER, idx || new Uint32Array([...Array(pos.length / 3).keys()]), gl.STATIC_DRAW);
          prims.push(b);
        }
      }
      let maxR = 0.001;
      for (const p of prims) { /* 粗估尺寸：用第一个 primitive 的包围盒 */ }
      const a = gltf.accessors.find(x => x.type === 'VEC3' && x.min && x.max);
      if (a) maxR = Math.max(...[0,1,2].map(i => Math.abs(a.max[i] - a.min[i])));
      radius = maxR * 0.75 || 3;
      dirty = true;
    }

    function draw() {
      if (!alive) return;
      const dpr = Math.min(devicePixelRatio || 1, 2);
      const w = canvas.clientWidth * dpr | 0, h = canvas.clientHeight * dpr | 0;
      if (canvas.width !== w || canvas.height !== h) { canvas.width = w; canvas.height = h; dirty = true; }
      if (spin) { yaw += 0.008; dirty = true; }
      if (dirty) {
        gl.viewport(0, 0, w, h);
        gl.clearColor(0.028, 0.035, 0.055, 1); gl.clear(gl.COLOR_BUFFER_BIT | gl.DEPTH_BUFFER_BIT);
        gl.enable(gl.DEPTH_TEST);
        const eye = [Math.cos(pitch) * Math.sin(yaw), Math.sin(pitch), Math.cos(pitch) * Math.cos(yaw)]
          .map(v => v * radius * 2.6 * dist);
        const view = lookAt(eye, [0, 0, 0], [0, 1, 0]);
        const mvp = mat4Mul(perspective(0.9, (w / h) || 1, 0.01, 1000), view);
        gl.useProgram(prog);
        gl.uniformMatrix4fv(U.mvp, false, mvp);
        gl.uniformMatrix3fv(U.normal, false, new Float32Array([1,0,0, 0,1,0, 0,0,1]));
        gl.uniform3fv(U.light, [0.45, 0.75, 0.5]);
        for (const p of prims) {
          gl.bindBuffer(gl.ARRAY_BUFFER, p.pos);
          const aPos = gl.getAttribLocation(prog, 'aPos');
          gl.enableVertexAttribArray(aPos); gl.vertexAttribPointer(aPos, 3, gl.FLOAT, false, 0, 0);
          gl.bindBuffer(gl.ARRAY_BUFFER, p.nrm);
          const aNrm = gl.getAttribLocation(prog, 'aNrm');
          gl.enableVertexAttribArray(aNrm); gl.vertexAttribPointer(aNrm, 3, gl.FLOAT, false, 0, 0);
          gl.uniform3fv(U.color, p.color);
          gl.bindBuffer(gl.ELEMENT_ARRAY_BUFFER, p.idx);
          gl.drawElements(gl.TRIANGLES, p.count, gl.UNSIGNED_INT, 0);
        }
        dirty = false;
      }
      requestAnimationFrame(draw);
    }

    // 自检：画了几帧后采样一次；若与背景色完全一致，说明没画出东西
    let framesDrawn = 0, checked = false;
    const origDraw = draw;
    function drawWithCheck() {
      origDraw();
      framesDrawn++;
      if (!checked && framesDrawn > 3) {
        checked = true;
        try {
          const px = new Uint8Array(4 * 16);
          gl.readPixels(0, 0, 4, 4, gl.RGBA, gl.UNSIGNED_BYTE, px);
          let nonBg = 0;
          for (let i = 0; i < px.length; i += 4) {
            if (Math.abs(px[i] - 7) > 4 || Math.abs(px[i + 1] - 9) > 4 || Math.abs(px[i + 2] - 14) > 4) nonBg++;
          }
          if (nonBg === 0) { throw new Error('WebGL 画布没有内容'); }
        } catch (e) {
          window.dispatchEvent(new CustomEvent('sf-viewer-empty', { detail: e.message }));
        }
      }
    }
    // 用带自检的循环替换
    function loop() { if (!alive) return; drawWithCheck(); }
    requestAnimationFrame(loop);

    // 交互
    let dragging = false, lx = 0, ly = 0;
    canvas.addEventListener('pointerdown', e => { dragging = true; lx = e.clientX; ly = e.clientY; canvas.style.cursor = 'grabbing'; });
    addEventListener('pointerup', () => { dragging = false; canvas.style.cursor = 'grab'; });
    addEventListener('pointermove', e => {
      if (!dragging) return;
      yaw -= (e.clientX - lx) * 0.01; pitch = Math.max(-1.4, Math.min(1.4, pitch + (e.clientY - ly) * 0.01));
      lx = e.clientX; ly = e.clientY; dirty = true;
    });
    canvas.addEventListener('wheel', e => { e.preventDefault(); dist = Math.max(0.35, Math.min(4, dist * (1 + Math.sign(e.deltaY) * 0.1))); dirty = true; }, { passive: false });

    return {
      async load(url) {
        const r = await fetch(url); if (!r.ok) throw new Error((await r.json().catch(() => ({}))).error?.message || r.status);
        const buf = await r.arrayBuffer();
        const { json, bin } = parseGlb(buf);
        upload(json, bin);
        return { prims: prims.length, bytes: buf.byteLength };
      },
      setView(v) { if (v === 'top') { pitch = 1.35; } else if (v === 'side') { pitch = 0.05; yaw = Math.PI / 2; } else { pitch = 0.35; yaw = 0.6; } dirty = true; },
      spin(on) { spin = on; dirty = true; },
      dispose() { alive = false; }
    };
  }

  window.StarforgeViewer = { mount };
})();
