//#region node_modules/@lit/reactive-element/css-tag.js
var e = globalThis, t = e.ShadowRoot && (e.ShadyCSS === void 0 || e.ShadyCSS.nativeShadow) && "adoptedStyleSheets" in Document.prototype && "replace" in CSSStyleSheet.prototype, n = Symbol(), r = /* @__PURE__ */ new WeakMap(), i = class {
	constructor(e, t, r) {
		if (this._$cssResult$ = !0, r !== n) throw Error("CSSResult is not constructable. Use `unsafeCSS` or `css` instead.");
		this.cssText = e, this.t = t;
	}
	get styleSheet() {
		let e = this.o, n = this.t;
		if (t && e === void 0) {
			let t = n !== void 0 && n.length === 1;
			t && (e = r.get(n)), e === void 0 && ((this.o = e = new CSSStyleSheet()).replaceSync(this.cssText), t && r.set(n, e));
		}
		return e;
	}
	toString() {
		return this.cssText;
	}
}, a = (e) => new i(typeof e == "string" ? e : e + "", void 0, n), o = (e, ...t) => new i(e.length === 1 ? e[0] : t.reduce((t, n, r) => t + ((e) => {
	if (!0 === e._$cssResult$) return e.cssText;
	if (typeof e == "number") return e;
	throw Error("Value passed to 'css' function must be a 'css' function result: " + e + ". Use 'unsafeCSS' to pass non-literal values, but take care to ensure page security.");
})(n) + e[r + 1], e[0]), e, n), s = (n, r) => {
	if (t) n.adoptedStyleSheets = r.map((e) => e instanceof CSSStyleSheet ? e : e.styleSheet);
	else for (let t of r) {
		let r = document.createElement("style"), i = e.litNonce;
		i !== void 0 && r.setAttribute("nonce", i), r.textContent = t.cssText, n.appendChild(r);
	}
}, c = t ? (e) => e : (e) => e instanceof CSSStyleSheet ? ((e) => {
	let t = "";
	for (let n of e.cssRules) t += n.cssText;
	return a(t);
})(e) : e, { is: l, defineProperty: u, getOwnPropertyDescriptor: d, getOwnPropertyNames: ee, getOwnPropertySymbols: te, getPrototypeOf: ne } = Object, f = globalThis, p = f.trustedTypes, re = p ? p.emptyScript : "", ie = f.reactiveElementPolyfillSupport, m = (e, t) => e, h = {
	toAttribute(e, t) {
		switch (t) {
			case Boolean:
				e = e ? re : null;
				break;
			case Object:
			case Array: e = e == null ? e : JSON.stringify(e);
		}
		return e;
	},
	fromAttribute(e, t) {
		let n = e;
		switch (t) {
			case Boolean:
				n = e !== null;
				break;
			case Number:
				n = e === null ? null : Number(e);
				break;
			case Object:
			case Array: try {
				n = JSON.parse(e);
			} catch {
				n = null;
			}
		}
		return n;
	}
}, g = (e, t) => !l(e, t), _ = {
	attribute: !0,
	type: String,
	converter: h,
	reflect: !1,
	useDefault: !1,
	hasChanged: g
};
Symbol.metadata ??= Symbol("metadata"), f.litPropertyMetadata ??= /* @__PURE__ */ new WeakMap();
var v = class extends HTMLElement {
	static addInitializer(e) {
		this._$Ei(), (this.l ??= []).push(e);
	}
	static get observedAttributes() {
		return this.finalize(), this._$Eh && [...this._$Eh.keys()];
	}
	static createProperty(e, t = _) {
		if (t.state && (t.attribute = !1), this._$Ei(), this.prototype.hasOwnProperty(e) && ((t = Object.create(t)).wrapped = !0), this.elementProperties.set(e, t), !t.noAccessor) {
			let n = Symbol(), r = this.getPropertyDescriptor(e, n, t);
			r !== void 0 && u(this.prototype, e, r);
		}
	}
	static getPropertyDescriptor(e, t, n) {
		let { get: r, set: i } = d(this.prototype, e) ?? {
			get() {
				return this[t];
			},
			set(e) {
				this[t] = e;
			}
		};
		return {
			get: r,
			set(t) {
				let a = r?.call(this);
				i?.call(this, t), this.requestUpdate(e, a, n);
			},
			configurable: !0,
			enumerable: !0
		};
	}
	static getPropertyOptions(e) {
		return this.elementProperties.get(e) ?? _;
	}
	static _$Ei() {
		if (this.hasOwnProperty(m("elementProperties"))) return;
		let e = ne(this);
		e.finalize(), e.l !== void 0 && (this.l = [...e.l]), this.elementProperties = new Map(e.elementProperties);
	}
	static finalize() {
		if (this.hasOwnProperty(m("finalized"))) return;
		if (this.finalized = !0, this._$Ei(), this.hasOwnProperty(m("properties"))) {
			let e = this.properties, t = [...ee(e), ...te(e)];
			for (let n of t) this.createProperty(n, e[n]);
		}
		let e = this[Symbol.metadata];
		if (e !== null) {
			let t = litPropertyMetadata.get(e);
			if (t !== void 0) for (let [e, n] of t) this.elementProperties.set(e, n);
		}
		this._$Eh = /* @__PURE__ */ new Map();
		for (let [e, t] of this.elementProperties) {
			let n = this._$Eu(e, t);
			n !== void 0 && this._$Eh.set(n, e);
		}
		this.elementStyles = this.finalizeStyles(this.styles);
	}
	static finalizeStyles(e) {
		let t = [];
		if (Array.isArray(e)) {
			let n = new Set(e.flat(1 / 0).reverse());
			for (let e of n) t.unshift(c(e));
		} else e !== void 0 && t.push(c(e));
		return t;
	}
	static _$Eu(e, t) {
		let n = t.attribute;
		return !1 === n ? void 0 : typeof n == "string" ? n : typeof e == "string" ? e.toLowerCase() : void 0;
	}
	constructor() {
		super(), this._$Ep = void 0, this.isUpdatePending = !1, this.hasUpdated = !1, this._$Em = null, this._$Ev();
	}
	_$Ev() {
		this._$ES = new Promise((e) => this.enableUpdating = e), this._$AL = /* @__PURE__ */ new Map(), this._$E_(), this.requestUpdate(), this.constructor.l?.forEach((e) => e(this));
	}
	addController(e) {
		(this._$EO ??= /* @__PURE__ */ new Set()).add(e), this.renderRoot !== void 0 && this.isConnected && e.hostConnected?.();
	}
	removeController(e) {
		this._$EO?.delete(e);
	}
	_$E_() {
		let e = /* @__PURE__ */ new Map(), t = this.constructor.elementProperties;
		for (let n of t.keys()) this.hasOwnProperty(n) && (e.set(n, this[n]), delete this[n]);
		e.size > 0 && (this._$Ep = e);
	}
	createRenderRoot() {
		let e = this.shadowRoot ?? this.attachShadow(this.constructor.shadowRootOptions);
		return s(e, this.constructor.elementStyles), e;
	}
	connectedCallback() {
		this.renderRoot ??= this.createRenderRoot(), this.enableUpdating(!0), this._$EO?.forEach((e) => e.hostConnected?.());
	}
	enableUpdating(e) {}
	disconnectedCallback() {
		this._$EO?.forEach((e) => e.hostDisconnected?.());
	}
	attributeChangedCallback(e, t, n) {
		this._$AK(e, n);
	}
	_$ET(e, t) {
		let n = this.constructor.elementProperties.get(e), r = this.constructor._$Eu(e, n);
		if (r !== void 0 && !0 === n.reflect) {
			let i = (n.converter?.toAttribute === void 0 ? h : n.converter).toAttribute(t, n.type);
			this._$Em = e, i == null ? this.removeAttribute(r) : this.setAttribute(r, i), this._$Em = null;
		}
	}
	_$AK(e, t) {
		let n = this.constructor, r = n._$Eh.get(e);
		if (r !== void 0 && this._$Em !== r) {
			let e = n.getPropertyOptions(r), i = typeof e.converter == "function" ? { fromAttribute: e.converter } : e.converter?.fromAttribute === void 0 ? h : e.converter;
			this._$Em = r;
			let a = i.fromAttribute(t, e.type);
			this[r] = a ?? this._$Ej?.get(r) ?? a, this._$Em = null;
		}
	}
	requestUpdate(e, t, n, r = !1, i) {
		if (e !== void 0) {
			let a = this.constructor;
			if (!1 === r && (i = this[e]), n ??= a.getPropertyOptions(e), !((n.hasChanged ?? g)(i, t) || n.useDefault && n.reflect && i === this._$Ej?.get(e) && !this.hasAttribute(a._$Eu(e, n)))) return;
			this.C(e, t, n);
		}
		!1 === this.isUpdatePending && (this._$ES = this._$EP());
	}
	C(e, t, { useDefault: n, reflect: r, wrapped: i }, a) {
		n && !(this._$Ej ??= /* @__PURE__ */ new Map()).has(e) && (this._$Ej.set(e, a ?? t ?? this[e]), !0 !== i || a !== void 0) || (this._$AL.has(e) || (this.hasUpdated || n || (t = void 0), this._$AL.set(e, t)), !0 === r && this._$Em !== e && (this._$Eq ??= /* @__PURE__ */ new Set()).add(e));
	}
	async _$EP() {
		this.isUpdatePending = !0;
		try {
			await this._$ES;
		} catch (e) {
			Promise.reject(e);
		}
		let e = this.scheduleUpdate();
		return e != null && await e, !this.isUpdatePending;
	}
	scheduleUpdate() {
		return this.performUpdate();
	}
	performUpdate() {
		if (!this.isUpdatePending) return;
		if (!this.hasUpdated) {
			if (this.renderRoot ??= this.createRenderRoot(), this._$Ep) {
				for (let [e, t] of this._$Ep) this[e] = t;
				this._$Ep = void 0;
			}
			let e = this.constructor.elementProperties;
			if (e.size > 0) for (let [t, n] of e) {
				let { wrapped: e } = n, r = this[t];
				!0 !== e || this._$AL.has(t) || r === void 0 || this.C(t, void 0, n, r);
			}
		}
		let e = !1, t = this._$AL;
		try {
			e = this.shouldUpdate(t), e ? (this.willUpdate(t), this._$EO?.forEach((e) => e.hostUpdate?.()), this.update(t)) : this._$EM();
		} catch (t) {
			throw e = !1, this._$EM(), t;
		}
		e && this._$AE(t);
	}
	willUpdate(e) {}
	_$AE(e) {
		this._$EO?.forEach((e) => e.hostUpdated?.()), this.hasUpdated || (this.hasUpdated = !0, this.firstUpdated(e)), this.updated(e);
	}
	_$EM() {
		this._$AL = /* @__PURE__ */ new Map(), this.isUpdatePending = !1;
	}
	get updateComplete() {
		return this.getUpdateComplete();
	}
	getUpdateComplete() {
		return this._$ES;
	}
	shouldUpdate(e) {
		return !0;
	}
	update(e) {
		this._$Eq &&= this._$Eq.forEach((e) => this._$ET(e, this[e])), this._$EM();
	}
	updated(e) {}
	firstUpdated(e) {}
};
v.elementStyles = [], v.shadowRootOptions = { mode: "open" }, v[m("elementProperties")] = /* @__PURE__ */ new Map(), v[m("finalized")] = /* @__PURE__ */ new Map(), ie?.({ ReactiveElement: v }), (f.reactiveElementVersions ??= []).push("2.1.2");
//#endregion
//#region node_modules/lit-html/lit-html.js
var y = globalThis, ae = (e) => e, b = y.trustedTypes, x = b ? b.createPolicy("lit-html", { createHTML: (e) => e }) : void 0, S = "$lit$", C = `lit$${Math.random().toFixed(9).slice(2)}$`, w = "?" + C, oe = `<${w}>`, T = document, E = () => T.createComment(""), D = (e) => e === null || typeof e != "object" && typeof e != "function", O = Array.isArray, se = (e) => O(e) || typeof e?.[Symbol.iterator] == "function", k = "[ 	\n\f\r]", A = /<(?:(!--|\/[^a-zA-Z])|(\/?[a-zA-Z][^>\s]*)|(\/?$))/g, j = /-->/g, M = />/g, N = RegExp(`>|${k}(?:([^\\s"'>=/]+)(${k}*=${k}*(?:[^ \t\n\f\r"'\`<>=]|("|')|))|$)`, "g"), P = /'/g, F = /"/g, I = /^(?:script|style|textarea|title)$/i, L = ((e) => (t, ...n) => ({
	_$litType$: e,
	strings: t,
	values: n
}))(1), R = Symbol.for("lit-noChange"), z = Symbol.for("lit-nothing"), B = /* @__PURE__ */ new WeakMap(), V = T.createTreeWalker(T, 129);
function H(e, t) {
	if (!O(e) || !e.hasOwnProperty("raw")) throw Error("invalid template strings array");
	return x === void 0 ? t : x.createHTML(t);
}
var ce = (e, t) => {
	let n = e.length - 1, r = [], i, a = t === 2 ? "<svg>" : t === 3 ? "<math>" : "", o = A;
	for (let t = 0; t < n; t++) {
		let n = e[t], s, c, l = -1, u = 0;
		for (; u < n.length && (o.lastIndex = u, c = o.exec(n), c !== null);) u = o.lastIndex, o === A ? c[1] === "!--" ? o = j : c[1] === void 0 ? c[2] === void 0 ? c[3] !== void 0 && (o = N) : (I.test(c[2]) && (i = RegExp("</" + c[2], "g")), o = N) : o = M : o === N ? c[0] === ">" ? (o = i ?? A, l = -1) : c[1] === void 0 ? l = -2 : (l = o.lastIndex - c[2].length, s = c[1], o = c[3] === void 0 ? N : c[3] === "\"" ? F : P) : o === F || o === P ? o = N : o === j || o === M ? o = A : (o = N, i = void 0);
		let d = o === N && e[t + 1].startsWith("/>") ? " " : "";
		a += o === A ? n + oe : l >= 0 ? (r.push(s), n.slice(0, l) + S + n.slice(l) + C + d) : n + C + (l === -2 ? t : d);
	}
	return [H(e, a + (e[n] || "<?>") + (t === 2 ? "</svg>" : t === 3 ? "</math>" : "")), r];
}, U = class e {
	constructor({ strings: t, _$litType$: n }, r) {
		let i;
		this.parts = [];
		let a = 0, o = 0, s = t.length - 1, c = this.parts, [l, u] = ce(t, n);
		if (this.el = e.createElement(l, r), V.currentNode = this.el.content, n === 2 || n === 3) {
			let e = this.el.content.firstChild;
			e.replaceWith(...e.childNodes);
		}
		for (; (i = V.nextNode()) !== null && c.length < s;) {
			if (i.nodeType === 1) {
				if (i.hasAttributes()) for (let e of i.getAttributeNames()) if (e.endsWith(S)) {
					let t = u[o++], n = i.getAttribute(e).split(C), r = /([.?@])?(.*)/.exec(t);
					c.push({
						type: 1,
						index: a,
						name: r[2],
						strings: n,
						ctor: r[1] === "." ? ue : r[1] === "?" ? de : r[1] === "@" ? fe : K
					}), i.removeAttribute(e);
				} else e.startsWith(C) && (c.push({
					type: 6,
					index: a
				}), i.removeAttribute(e));
				if (I.test(i.tagName)) {
					let e = i.textContent.split(C), t = e.length - 1;
					if (t > 0) {
						i.textContent = b ? b.emptyScript : "";
						for (let n = 0; n < t; n++) i.append(e[n], E()), V.nextNode(), c.push({
							type: 2,
							index: ++a
						});
						i.append(e[t], E());
					}
				}
			} else if (i.nodeType === 8) {
				if (i.data === w) c.push({
					type: 2,
					index: a
				});
				else {
					let e = -1;
					for (; (e = i.data.indexOf(C, e + 1)) !== -1;) c.push({
						type: 7,
						index: a
					}), e += C.length - 1;
				}
			}
			a++;
		}
	}
	static createElement(e, t) {
		let n = T.createElement("template");
		return n.innerHTML = e, n;
	}
};
function W(e, t, n = e, r) {
	if (t === R) return t;
	let i = r === void 0 ? n._$Cl : n._$Co?.[r], a = D(t) ? void 0 : t._$litDirective$;
	return i?.constructor !== a && (i?._$AO?.(!1), a === void 0 ? i = void 0 : (i = new a(e), i._$AT(e, n, r)), r === void 0 ? n._$Cl = i : (n._$Co ??= [])[r] = i), i !== void 0 && (t = W(e, i._$AS(e, t.values), i, r)), t;
}
var le = class {
	constructor(e, t) {
		this._$AV = [], this._$AN = void 0, this._$AD = e, this._$AM = t;
	}
	get parentNode() {
		return this._$AM.parentNode;
	}
	get _$AU() {
		return this._$AM._$AU;
	}
	u(e) {
		let { el: { content: t }, parts: n } = this._$AD, r = (e?.creationScope ?? T).importNode(t, !0);
		V.currentNode = r;
		let i = V.nextNode(), a = 0, o = 0, s = n[0];
		for (; s !== void 0;) {
			if (a === s.index) {
				let t;
				s.type === 2 ? t = new G(i, i.nextSibling, this, e) : s.type === 1 ? t = new s.ctor(i, s.name, s.strings, this, e) : s.type === 6 && (t = new pe(i, this, e)), this._$AV.push(t), s = n[++o];
			}
			a !== s?.index && (i = V.nextNode(), a++);
		}
		return V.currentNode = T, r;
	}
	p(e) {
		let t = 0;
		for (let n of this._$AV) n !== void 0 && (n.strings === void 0 ? n._$AI(e[t]) : (n._$AI(e, n, t), t += n.strings.length - 2)), t++;
	}
}, G = class e {
	get _$AU() {
		return this._$AM?._$AU ?? this._$Cv;
	}
	constructor(e, t, n, r) {
		this.type = 2, this._$AH = z, this._$AN = void 0, this._$AA = e, this._$AB = t, this._$AM = n, this.options = r, this._$Cv = r?.isConnected ?? !0;
	}
	get parentNode() {
		let e = this._$AA.parentNode, t = this._$AM;
		return t !== void 0 && e?.nodeType === 11 && (e = t.parentNode), e;
	}
	get startNode() {
		return this._$AA;
	}
	get endNode() {
		return this._$AB;
	}
	_$AI(e, t = this) {
		e = W(this, e, t), D(e) ? e === z || e == null || e === "" ? (this._$AH !== z && this._$AR(), this._$AH = z) : e !== this._$AH && e !== R && this._(e) : e._$litType$ === void 0 ? e.nodeType === void 0 ? se(e) ? this.k(e) : this._(e) : this.T(e) : this.$(e);
	}
	O(e) {
		return this._$AA.parentNode.insertBefore(e, this._$AB);
	}
	T(e) {
		this._$AH !== e && (this._$AR(), this._$AH = this.O(e));
	}
	_(e) {
		this._$AH !== z && D(this._$AH) ? this._$AA.nextSibling.data = e : this.T(T.createTextNode(e)), this._$AH = e;
	}
	$(e) {
		let { values: t, _$litType$: n } = e, r = typeof n == "number" ? this._$AC(e) : (n.el === void 0 && (n.el = U.createElement(H(n.h, n.h[0]), this.options)), n);
		if (this._$AH?._$AD === r) this._$AH.p(t);
		else {
			let e = new le(r, this), n = e.u(this.options);
			e.p(t), this.T(n), this._$AH = e;
		}
	}
	_$AC(e) {
		let t = B.get(e.strings);
		return t === void 0 && B.set(e.strings, t = new U(e)), t;
	}
	k(t) {
		O(this._$AH) || (this._$AH = [], this._$AR());
		let n = this._$AH, r, i = 0;
		for (let a of t) i === n.length ? n.push(r = new e(this.O(E()), this.O(E()), this, this.options)) : r = n[i], r._$AI(a), i++;
		i < n.length && (this._$AR(r && r._$AB.nextSibling, i), n.length = i);
	}
	_$AR(e = this._$AA.nextSibling, t) {
		for (this._$AP?.(!1, !0, t); e !== this._$AB;) {
			let t = ae(e).nextSibling;
			ae(e).remove(), e = t;
		}
	}
	setConnected(e) {
		this._$AM === void 0 && (this._$Cv = e, this._$AP?.(e));
	}
}, K = class {
	get tagName() {
		return this.element.tagName;
	}
	get _$AU() {
		return this._$AM._$AU;
	}
	constructor(e, t, n, r, i) {
		this.type = 1, this._$AH = z, this._$AN = void 0, this.element = e, this.name = t, this._$AM = r, this.options = i, n.length > 2 || n[0] !== "" || n[1] !== "" ? (this._$AH = Array(n.length - 1).fill(/* @__PURE__ */ new String()), this.strings = n) : this._$AH = z;
	}
	_$AI(e, t = this, n, r) {
		let i = this.strings, a = !1;
		if (i === void 0) e = W(this, e, t, 0), a = !D(e) || e !== this._$AH && e !== R, a && (this._$AH = e);
		else {
			let r = e, o, s;
			for (e = i[0], o = 0; o < i.length - 1; o++) s = W(this, r[n + o], t, o), s === R && (s = this._$AH[o]), a ||= !D(s) || s !== this._$AH[o], s === z ? e = z : e !== z && (e += (s ?? "") + i[o + 1]), this._$AH[o] = s;
		}
		a && !r && this.j(e);
	}
	j(e) {
		e === z ? this.element.removeAttribute(this.name) : this.element.setAttribute(this.name, e ?? "");
	}
}, ue = class extends K {
	constructor() {
		super(...arguments), this.type = 3;
	}
	j(e) {
		this.element[this.name] = e === z ? void 0 : e;
	}
}, de = class extends K {
	constructor() {
		super(...arguments), this.type = 4;
	}
	j(e) {
		this.element.toggleAttribute(this.name, !!e && e !== z);
	}
}, fe = class extends K {
	constructor(e, t, n, r, i) {
		super(e, t, n, r, i), this.type = 5;
	}
	_$AI(e, t = this) {
		if ((e = W(this, e, t, 0) ?? z) === R) return;
		let n = this._$AH, r = e === z && n !== z || e.capture !== n.capture || e.once !== n.once || e.passive !== n.passive, i = e !== z && (n === z || r);
		r && this.element.removeEventListener(this.name, this, n), i && this.element.addEventListener(this.name, this, e), this._$AH = e;
	}
	handleEvent(e) {
		typeof this._$AH == "function" ? this._$AH.call(this.options?.host ?? this.element, e) : this._$AH.handleEvent(e);
	}
}, pe = class {
	constructor(e, t, n) {
		this.element = e, this.type = 6, this._$AN = void 0, this._$AM = t, this.options = n;
	}
	get _$AU() {
		return this._$AM._$AU;
	}
	_$AI(e) {
		W(this, e);
	}
}, me = y.litHtmlPolyfillSupport;
me?.(U, G), (y.litHtmlVersions ??= []).push("3.3.3");
var he = (e, t, n) => {
	let r = n?.renderBefore ?? t, i = r._$litPart$;
	if (i === void 0) {
		let e = n?.renderBefore ?? null;
		r._$litPart$ = i = new G(t.insertBefore(E(), e), e, void 0, n ?? {});
	}
	return i._$AI(e), i;
}, q = globalThis, J = class extends v {
	constructor() {
		super(...arguments), this.renderOptions = { host: this }, this._$Do = void 0;
	}
	createRenderRoot() {
		let e = super.createRenderRoot();
		return this.renderOptions.renderBefore ??= e.firstChild, e;
	}
	update(e) {
		let t = this.render();
		this.hasUpdated || (this.renderOptions.isConnected = this.isConnected), super.update(e), this._$Do = he(t, this.renderRoot, this.renderOptions);
	}
	connectedCallback() {
		super.connectedCallback(), this._$Do?.setConnected(!0);
	}
	disconnectedCallback() {
		super.disconnectedCallback(), this._$Do?.setConnected(!1);
	}
	render() {
		return R;
	}
};
J._$litElement$ = !0, J.finalized = !0, q.litElementHydrateSupport?.({ LitElement: J });
var ge = q.litElementPolyfillSupport;
ge?.({ LitElement: J }), (q.litElementVersions ??= []).push("4.2.2");
//#endregion
//#region src/helpers.ts
function _e(e, t) {
	let n = e.entities?.[t]?.device_id;
	if (n) {
		for (let t of Object.values(e.entities ?? {})) if (t.device_id === n && t.entity_id.startsWith("remote.")) return t.entity_id;
	}
	let r = `remote.${t.split(".", 2)[1]}`;
	return e.states[r] ? r : void 0;
}
function ve(e, t) {
	return t && t.length > 0 ? t.filter((t) => e.states[t]) : Object.keys(e.states).filter((e) => e.startsWith("camera.")).sort((t, n) => Y(e, t).localeCompare(Y(e, n)));
}
function Y(e, t) {
	let n = e.states[t]?.attributes.friendly_name;
	return typeof n == "string" && n ? n : t;
}
function ye(e) {
	let t = e.trim().split(/\s+/).filter(Boolean);
	if (t.length === 0) return "?";
	let n = Array.from(t[0])[0] ?? "?";
	return (n + (/^[A-Za-z0-9]/.test(n) && t.length > 1 ? Array.from(t[1])[0] ?? "" : "")).toUpperCase();
}
function be(e) {
	let t = 0;
	for (let n of e) t = t * 31 + (n.codePointAt(0) ?? 0) | 0;
	return `hsl(${Math.abs(t) % 360} 55% 46%)`;
}
//#endregion
//#region src/strings.ts
var X = {
	en: {
		off: "Off",
		home: "Home",
		power: "Power",
		cameras: "Cameras",
		showCamera: "Show on TV",
		stop: "Stop",
		message: "Message",
		messagePlaceholder: "Text to show on the TV",
		title: "Title",
		duration: "Duration",
		seconds: "s",
		showMessage: "Full-screen message",
		updateText: "Update text",
		info: "Info",
		warning: "Warning",
		alert: "Alert",
		apps: "Apps",
		remote: "Remote",
		back: "Back",
		ok: "OK",
		volumeDown: "Volume down",
		volumeUp: "Volume up",
		mute: "Mute",
		playPause: "Play / pause",
		noCameras: "No cameras in Home Assistant yet.",
		sent: "Sent to the TV",
		failed: "Failed"
	},
	ar: {
		off: "مطفأ",
		home: "الرئيسية",
		power: "التشغيل",
		cameras: "الكاميرات",
		showCamera: "اعرض على التلفاز",
		stop: "إيقاف",
		message: "الرسالة",
		messagePlaceholder: "نص يظهر على التلفاز",
		title: "العنوان",
		duration: "المدة",
		seconds: "ث",
		showMessage: "رسالة بملء الشاشة",
		updateText: "تحديث النص",
		info: "معلومة",
		warning: "تحذير",
		alert: "تنبيه",
		apps: "التطبيقات",
		remote: "جهاز التحكم",
		back: "رجوع",
		ok: "موافق",
		volumeDown: "خفض الصوت",
		volumeUp: "رفع الصوت",
		mute: "كتم",
		playPause: "تشغيل / إيقاف مؤقت",
		noCameras: "لا توجد كاميرات في Home Assistant بعد.",
		sent: "أُرسل إلى التلفاز",
		failed: "فشل"
	}
};
function Z(e) {
	return e?.toLowerCase().startsWith("ar") ? "ar" : "en";
}
function xe(e) {
	return X[e];
}
Object.keys(X);
//#endregion
//#region src/samstream-card.ts
var Q, Se = [
	"info",
	"warning",
	"alert"
], Ce = 3e3, $ = class extends J {
	constructor(...e) {
		super(...e), this.camera = "", this.feedback = "", this.severity = "info";
	}
	setConfig(e) {
		if (!e.entity) throw Error("Choose the Samstream TV (media player).");
		this.config = e;
	}
	getCardSize() {
		return 8;
	}
	static getConfigForm() {
		return { schema: [
			{
				name: "entity",
				required: !0,
				selector: { entity: {
					domain: "media_player",
					integration: "samstream"
				} }
			},
			{
				name: "cameras",
				selector: { entity: {
					domain: "camera",
					multiple: !0
				} }
			},
			{
				type: "grid",
				name: "",
				schema: [
					{
						name: "show_cameras",
						selector: { boolean: {} }
					},
					{
						name: "show_message",
						selector: { boolean: {} }
					},
					{
						name: "show_apps",
						selector: { boolean: {} }
					},
					{
						name: "show_remote",
						selector: { boolean: {} }
					}
				]
			}
		] };
	}
	static getStubConfig(e) {
		return { entity: Object.values(e.entities ?? {}).find((e) => e.platform === "samstream" && e.entity_id.startsWith("media_player."))?.entity_id ?? "" };
	}
	get text() {
		return xe(Z(this.hass?.locale?.language ?? this.hass?.language));
	}
	get rtl() {
		return Z(this.hass?.locale?.language ?? this.hass?.language) === "ar";
	}
	updated(e) {
		if (!e.has("hass") || !this.hass || !this.config) return;
		let t = this.hass.states[this.config.entity]?.attributes.app_id ?? null;
		(this.apps === void 0 || t !== this.appsFor) && (this.appsFor = t, this.loadApps());
	}
	loadApps() {
		this.hass.callWS({
			type: "samstream/apps",
			entity_id: this.config.entity
		}).then((e) => this.apps = e).catch(() => this.apps = {
			home: "Home",
			current: null,
			apps: []
		});
	}
	render() {
		if (!this.hass || !this.config) return z;
		let e = this.hass.states[this.config.entity];
		if (!e) return L`<ha-card><div class="empty">${this.config.entity}?</div></ha-card>`;
		let t = e.state !== "off" && e.state !== "unavailable", n = (e) => this.config[e] !== !1;
		return L`
      <ha-card dir=${this.rtl ? "rtl" : "ltr"}>
        ${this.renderHeader(t)}
        ${t && n("show_cameras") ? this.renderCameras() : z}
        ${t && n("show_message") ? this.renderMessage() : z}
        ${t && n("show_apps") ? this.renderApps() : z}
        ${t && n("show_remote") ? this.renderRemote() : z}
        ${this.feedback ? L`<div class="feedback">${this.feedback}</div>` : z}
      </ha-card>
    `;
	}
	renderHeader(e) {
		let t = this.text, n = this.hass.states[this.config.entity], r = n.attributes.source ?? "", i = n.attributes.app_id, a = this.apps?.apps.find((e) => e.id === i), o = e ? r === "Home" ? t.home : a?.name ?? r : t.off;
		return L`
      <div class="header">
        ${a ? this.tile(a, "small") : L`<div class="tv"><ha-icon icon="mdi:television"></ha-icon></div>`}
        <div class="titles">
          <div class="name">${Y(this.hass, this.config.entity)}</div>
          <div class="sub">${o}</div>
        </div>
        <button
          class="round ${e ? "on" : ""}"
          title=${t.power}
          @click=${() => this.call("media_player", "toggle", { entity_id: this.config.entity })}
        >
          <ha-icon icon="mdi:power"></ha-icon>
        </button>
      </div>
    `;
	}
	renderCameras() {
		let e = this.text, t = ve(this.hass, this.config.cameras);
		if (t.length === 0) return L`<section><h3>${e.cameras}</h3><p class="hint">${e.noCameras}</p></section>`;
		let n = t.includes(this.camera) ? this.camera : t[0];
		return L`
      <section>
        <h3>${e.cameras}</h3>
        <div class="chips">
          ${t.map((e) => L`<button
              class="chip ${e === n ? "selected" : ""}"
              @click=${() => this.camera = e}
            >
              <ha-icon icon="mdi:cctv"></ha-icon>${Y(this.hass, e)}
            </button>`)}
        </div>
        <div class="row">
          <input id="camera-message" dir="auto" placeholder=${e.messagePlaceholder} />
          <label class="duration"
            ><input id="camera-duration" type="number" min="1" placeholder="—" /><span
              >${e.seconds}</span
            ></label
          >
        </div>
        <div class="actions">
          <button class="primary" @click=${() => this.playCamera(n)}>
            <ha-icon icon="mdi:television-play"></ha-icon>${e.showCamera}
          </button>
          <button @click=${() => this.call("samstream", "stop_stream", { entity_id: this.config.entity })}>
            <ha-icon icon="mdi:stop"></ha-icon>${e.stop}
          </button>
        </div>
      </section>
    `;
	}
	renderMessage() {
		let e = this.text, t = {
			info: e.info,
			warning: e.warning,
			alert: e.alert
		};
		return L`
      <section>
        <h3>${e.message}</h3>
        <input id="notice-title" dir="auto" placeholder=${e.title} />
        <textarea id="notice-message" dir="auto" rows="2" placeholder=${e.messagePlaceholder}></textarea>
        <div class="row">
          <div class="chips">
            ${Se.map((e) => L`<button
                class="chip ${e} ${e === this.severity ? "selected" : ""}"
                @click=${() => this.severity = e}
              >
                ${t[e]}
              </button>`)}
          </div>
          <label class="duration"
            ><input id="notice-duration" type="number" min="1" placeholder="—" /><span
              >${e.seconds}</span
            ></label
          >
        </div>
        <div class="actions">
          <button class="primary" @click=${() => this.showNotice()}>
            <ha-icon icon="mdi:message-alert"></ha-icon>${e.showMessage}
          </button>
          <button @click=${() => this.updateText()}>
            <ha-icon icon="mdi:message-text"></ha-icon>${e.updateText}
          </button>
        </div>
      </section>
    `;
	}
	renderApps() {
		let e = this.text, t = this.hass.states[this.config.entity], n = t.attributes.app_id, r = t.attributes.source === "Home", i = {
			id: "__home__",
			name: e.home,
			logo: null
		};
		return L`
      <section>
        <h3>${e.apps}</h3>
        <div class="apps">
          <button
            class="app ${r ? "current" : ""}"
            @click=${() => this.selectSource(this.apps?.home ?? "Home")}
          >
            <div class="tile home"><ha-icon icon="mdi:home"></ha-icon></div>
            <span>${i.name}</span>
          </button>
          ${(this.apps?.apps ?? []).map((e) => L`<button
              class="app ${e.id === n ? "current" : ""}"
              title=${e.name}
              @click=${() => this.selectSource(e.name)}
            >
              ${this.tile(e, "large")}<span dir="auto">${e.name}</span>
            </button>`)}
        </div>
      </section>
    `;
	}
	renderRemote() {
		let e = this.text, t = (e, t, n, r = "") => L`<button class="key ${r}" title=${n} @click=${() => this.sendKey(e)}>
        <ha-icon icon=${t}></ha-icon>
      </button>`;
		return L`
      <section>
        <h3>${e.remote}</h3>
        <div class="remote">
          <div class="pad">
            <span></span>${t("KEY_UP", "mdi:chevron-up", "▲")}<span></span>
            ${t(this.rtl ? "KEY_RIGHT" : "KEY_LEFT", this.rtl ? "mdi:chevron-right" : "mdi:chevron-left", "◀")}
            <button class="key ok" @click=${() => this.sendKey("KEY_ENTER")}>${e.ok}</button>
            ${t(this.rtl ? "KEY_LEFT" : "KEY_RIGHT", this.rtl ? "mdi:chevron-left" : "mdi:chevron-right", "▶")}
            <span></span>${t("KEY_DOWN", "mdi:chevron-down", "▼")}<span></span>
          </div>
          <div class="side">
            ${t("KEY_RETURN", "mdi:arrow-u-left-top", e.back)}
            ${t("KEY_HOME", "mdi:home", e.home)}
            <button class="key" title=${e.playPause} @click=${() => this.call("media_player", "media_play_pause", { entity_id: this.config.entity })}>
              <ha-icon icon="mdi:play-pause"></ha-icon>
            </button>
          </div>
          <div class="side">
            <button class="key" title=${e.volumeUp} @click=${() => this.call("media_player", "volume_up", { entity_id: this.config.entity })}>
              <ha-icon icon="mdi:volume-plus"></ha-icon>
            </button>
            <button class="key" title=${e.mute} @click=${() => this.toggleMute()}>
              <ha-icon icon="mdi:volume-off"></ha-icon>
            </button>
            <button class="key" title=${e.volumeDown} @click=${() => this.call("media_player", "volume_down", { entity_id: this.config.entity })}>
              <ha-icon icon="mdi:volume-minus"></ha-icon>
            </button>
          </div>
        </div>
      </section>
    `;
	}
	tile(e, t) {
		return e.logo ? L`<div class="tile ${t}"><img src=${e.logo} alt="" loading="lazy" /></div>` : L`<div class="tile ${t} letter" style="background:${be(e.name)}">
      ${ye(e.name)}
    </div>`;
	}
	value(e) {
		return this.renderRoot.querySelector(`#${e}`)?.value.trim() ?? "";
	}
	duration(e) {
		let t = Number(this.value(e));
		return t > 0 ? t : void 0;
	}
	playCamera(e) {
		let t = this.value("camera-message"), n = this.duration("camera-duration");
		this.call("samstream", "play_stream", {
			entity_id: this.config.entity,
			camera: e,
			...t ? { message: t } : {},
			...n ? { duration: n } : {}
		});
	}
	showNotice() {
		let e = this.value("notice-title"), t = this.value("notice-message");
		if (!e && !t) return;
		let n = this.duration("notice-duration");
		this.call("samstream", "show_message", {
			entity_id: this.config.entity,
			title: e,
			message: t,
			severity: this.severity,
			...n ? { duration: n } : {}
		});
	}
	updateText() {
		let e = this.value("notice-message") || this.value("camera-message");
		e && this.call("samstream", "update_message", {
			entity_id: this.config.entity,
			message: e
		});
	}
	selectSource(e) {
		this.call("media_player", "select_source", {
			entity_id: this.config.entity,
			source: e
		});
	}
	sendKey(e) {
		let t = _e(this.hass, this.config.entity);
		t && this.call("remote", "send_command", {
			entity_id: t,
			command: e
		}, !1);
	}
	toggleMute() {
		let e = this.hass.states[this.config.entity]?.attributes.is_volume_muted === !0;
		this.call("media_player", "volume_mute", {
			entity_id: this.config.entity,
			is_volume_muted: !e
		});
	}
	call(e, t, n, r = !0) {
		this.hass.callService(e, t, n).then(() => r && t !== "toggle" && this.flash(this.text.sent), (e) => this.flash(`${this.text.failed}: ${e?.message ?? String(e)}`));
	}
	flash(e) {
		this.feedback = e, clearTimeout(this.feedbackTimer), this.feedbackTimer = setTimeout(() => this.feedback = "", Ce);
	}
};
Q = $, Q.properties = {
	hass: { attribute: !1 },
	config: { state: !0 },
	apps: { state: !0 },
	camera: { state: !0 },
	feedback: { state: !0 },
	severity: { state: !0 }
}, Q.styles = o`
    ha-card {
      padding: 16px;
      display: flex;
      flex-direction: column;
      gap: 16px;
    }
    .empty {
      padding: 8px;
      color: var(--error-color);
    }
    .header {
      display: flex;
      align-items: center;
      gap: 12px;
    }
    .tv {
      display: flex;
      align-items: center;
      justify-content: center;
      width: 44px;
      height: 44px;
      border-radius: 12px;
      background: var(--secondary-background-color);
      color: var(--primary-color);
    }
    .titles {
      flex: 1;
      min-width: 0;
    }
    .name {
      font-size: 1.15rem;
      font-weight: 500;
    }
    .sub {
      color: var(--secondary-text-color);
      font-size: 0.9rem;
      overflow: hidden;
      text-overflow: ellipsis;
      white-space: nowrap;
    }
    section {
      display: flex;
      flex-direction: column;
      gap: 10px;
      padding-top: 14px;
      border-top: 1px solid var(--divider-color);
    }
    h3 {
      margin: 0;
      font-size: 0.8rem;
      font-weight: 500;
      letter-spacing: 0.04em;
      text-transform: uppercase;
      color: var(--secondary-text-color);
    }
    button {
      font: inherit;
      color: inherit;
      cursor: pointer;
      border: 1px solid var(--divider-color);
      background: var(--card-background-color);
      border-radius: 10px;
      padding: 8px 14px;
      display: inline-flex;
      align-items: center;
      justify-content: center;
      gap: 6px;
    }
    button:hover {
      background: var(--secondary-background-color);
    }
    button.primary {
      background: var(--primary-color);
      border-color: var(--primary-color);
      color: var(--text-primary-color, #fff);
    }
    button.round {
      width: 44px;
      height: 44px;
      padding: 0;
      border-radius: 50%;
    }
    button.round.on {
      color: var(--primary-color);
    }
    ha-icon {
      --mdc-icon-size: 20px;
    }
    .chips {
      display: flex;
      flex-wrap: wrap;
      gap: 8px;
    }
    .chip {
      border-radius: 999px;
      padding: 6px 12px;
    }
    .chip.selected {
      border-color: var(--primary-color);
      background: color-mix(in srgb, var(--primary-color) 14%, transparent);
    }
    .chip.warning.selected {
      border-color: var(--warning-color);
      background: color-mix(in srgb, var(--warning-color) 16%, transparent);
    }
    .chip.alert.selected {
      border-color: var(--error-color);
      background: color-mix(in srgb, var(--error-color) 14%, transparent);
    }
    .row {
      display: flex;
      gap: 8px;
      align-items: center;
    }
    .row > input,
    .row > .chips {
      flex: 1;
    }
    input,
    textarea {
      font: inherit;
      color: var(--primary-text-color);
      background: var(--secondary-background-color);
      border: 1px solid transparent;
      border-radius: 10px;
      padding: 9px 12px;
      box-sizing: border-box;
      width: 100%;
    }
    input:focus,
    textarea:focus {
      outline: none;
      border-color: var(--primary-color);
    }
    textarea {
      resize: vertical;
    }
    .duration {
      display: flex;
      align-items: center;
      gap: 4px;
      color: var(--secondary-text-color);
    }
    .duration input {
      width: 76px;
    }
    .actions {
      display: flex;
      flex-wrap: wrap;
      gap: 8px;
    }
    .apps {
      display: grid;
      grid-template-columns: repeat(auto-fill, minmax(76px, 1fr));
      gap: 10px;
    }
    .app {
      flex-direction: column;
      border: none;
      background: none;
      padding: 6px 2px;
      gap: 6px;
      font-size: 0.78rem;
    }
    .app span {
      max-width: 100%;
      overflow: hidden;
      text-overflow: ellipsis;
      white-space: nowrap;
    }
    .app.current .tile {
      box-shadow:
        0 0 0 2px var(--card-background-color),
        0 0 0 4px var(--primary-color);
    }
    .tile {
      display: flex;
      align-items: center;
      justify-content: center;
      overflow: hidden;
      border-radius: 14px;
      background: var(--secondary-background-color);
      flex-shrink: 0;
    }
    .tile.large,
    .tile.home {
      width: 56px;
      height: 56px;
    }
    .tile.small {
      width: 44px;
      height: 44px;
      border-radius: 12px;
    }
    .tile img {
      width: 100%;
      height: 100%;
      object-fit: contain;
    }
    .tile.letter {
      color: #fff;
      font-weight: 600;
      font-size: 1.1rem;
    }
    .tile.home {
      color: var(--primary-color);
    }
    .remote {
      display: flex;
      justify-content: center;
      align-items: center;
      gap: 24px;
    }
    .pad {
      display: grid;
      grid-template-columns: repeat(3, 48px);
      grid-template-rows: repeat(3, 48px);
      gap: 6px;
    }
    .key {
      width: 48px;
      height: 48px;
      padding: 0;
      border-radius: 14px;
    }
    .key.ok {
      border-radius: 50%;
      font-weight: 600;
      background: var(--primary-color);
      border-color: var(--primary-color);
      color: var(--text-primary-color, #fff);
    }
    .side {
      display: flex;
      flex-direction: column;
      gap: 6px;
    }
    .hint {
      margin: 0;
      color: var(--secondary-text-color);
    }
    .feedback {
      font-size: 0.85rem;
      color: var(--secondary-text-color);
      text-align: center;
    }
  `, customElements.get("samstream-card") || (customElements.define("samstream-card", $), (window.customCards ??= []).push({
	type: "samstream-card",
	name: "Samstream",
	description: "Cameras, messages, apps and a remote for your Samsung TV.",
	preview: !0,
	documentationURL: "https://github.com/islamahmady/samstream"
}));
//#endregion
export { $ as SamstreamCard };
