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
var y = globalThis, ae = (e) => e, b = y.trustedTypes, x = b ? b.createPolicy("lit-html", { createHTML: (e) => e }) : void 0, S = "$lit$", C = `lit$${Math.random().toFixed(9).slice(2)}$`, w = "?" + C, oe = `<${w}>`, T = document, E = () => T.createComment(""), D = (e) => e === null || typeof e != "object" && typeof e != "function", O = Array.isArray, se = (e) => O(e) || typeof e?.[Symbol.iterator] == "function", k = "[ 	\n\f\r]", A = /<(?:(!--|\/[^a-zA-Z])|(\/?[a-zA-Z][^>\s]*)|(\/?$))/g, ce = /-->/g, le = />/g, j = RegExp(`>|${k}(?:([^\\s"'>=/]+)(${k}*=${k}*(?:[^ \t\n\f\r"'\`<>=]|("|')|))|$)`, "g"), ue = /'/g, M = /"/g, N = /^(?:script|style|textarea|title)$/i, P = ((e) => (t, ...n) => ({
	_$litType$: e,
	strings: t,
	values: n
}))(1), F = Symbol.for("lit-noChange"), I = Symbol.for("lit-nothing"), L = /* @__PURE__ */ new WeakMap(), R = T.createTreeWalker(T, 129);
function z(e, t) {
	if (!O(e) || !e.hasOwnProperty("raw")) throw Error("invalid template strings array");
	return x === void 0 ? t : x.createHTML(t);
}
var de = (e, t) => {
	let n = e.length - 1, r = [], i, a = t === 2 ? "<svg>" : t === 3 ? "<math>" : "", o = A;
	for (let t = 0; t < n; t++) {
		let n = e[t], s, c, l = -1, u = 0;
		for (; u < n.length && (o.lastIndex = u, c = o.exec(n), c !== null);) u = o.lastIndex, o === A ? c[1] === "!--" ? o = ce : c[1] === void 0 ? c[2] === void 0 ? c[3] !== void 0 && (o = j) : (N.test(c[2]) && (i = RegExp("</" + c[2], "g")), o = j) : o = le : o === j ? c[0] === ">" ? (o = i ?? A, l = -1) : c[1] === void 0 ? l = -2 : (l = o.lastIndex - c[2].length, s = c[1], o = c[3] === void 0 ? j : c[3] === "\"" ? M : ue) : o === M || o === ue ? o = j : o === ce || o === le ? o = A : (o = j, i = void 0);
		let d = o === j && e[t + 1].startsWith("/>") ? " " : "";
		a += o === A ? n + oe : l >= 0 ? (r.push(s), n.slice(0, l) + S + n.slice(l) + C + d) : n + C + (l === -2 ? t : d);
	}
	return [z(e, a + (e[n] || "<?>") + (t === 2 ? "</svg>" : t === 3 ? "</math>" : "")), r];
}, B = class e {
	constructor({ strings: t, _$litType$: n }, r) {
		let i;
		this.parts = [];
		let a = 0, o = 0, s = t.length - 1, c = this.parts, [l, u] = de(t, n);
		if (this.el = e.createElement(l, r), R.currentNode = this.el.content, n === 2 || n === 3) {
			let e = this.el.content.firstChild;
			e.replaceWith(...e.childNodes);
		}
		for (; (i = R.nextNode()) !== null && c.length < s;) {
			if (i.nodeType === 1) {
				if (i.hasAttributes()) for (let e of i.getAttributeNames()) if (e.endsWith(S)) {
					let t = u[o++], n = i.getAttribute(e).split(C), r = /([.?@])?(.*)/.exec(t);
					c.push({
						type: 1,
						index: a,
						name: r[2],
						strings: n,
						ctor: r[1] === "." ? pe : r[1] === "?" ? me : r[1] === "@" ? he : U
					}), i.removeAttribute(e);
				} else e.startsWith(C) && (c.push({
					type: 6,
					index: a
				}), i.removeAttribute(e));
				if (N.test(i.tagName)) {
					let e = i.textContent.split(C), t = e.length - 1;
					if (t > 0) {
						i.textContent = b ? b.emptyScript : "";
						for (let n = 0; n < t; n++) i.append(e[n], E()), R.nextNode(), c.push({
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
function V(e, t, n = e, r) {
	if (t === F) return t;
	let i = r === void 0 ? n._$Cl : n._$Co?.[r], a = D(t) ? void 0 : t._$litDirective$;
	return i?.constructor !== a && (i?._$AO?.(!1), a === void 0 ? i = void 0 : (i = new a(e), i._$AT(e, n, r)), r === void 0 ? n._$Cl = i : (n._$Co ??= [])[r] = i), i !== void 0 && (t = V(e, i._$AS(e, t.values), i, r)), t;
}
var fe = class {
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
		R.currentNode = r;
		let i = R.nextNode(), a = 0, o = 0, s = n[0];
		for (; s !== void 0;) {
			if (a === s.index) {
				let t;
				s.type === 2 ? t = new H(i, i.nextSibling, this, e) : s.type === 1 ? t = new s.ctor(i, s.name, s.strings, this, e) : s.type === 6 && (t = new ge(i, this, e)), this._$AV.push(t), s = n[++o];
			}
			a !== s?.index && (i = R.nextNode(), a++);
		}
		return R.currentNode = T, r;
	}
	p(e) {
		let t = 0;
		for (let n of this._$AV) n !== void 0 && (n.strings === void 0 ? n._$AI(e[t]) : (n._$AI(e, n, t), t += n.strings.length - 2)), t++;
	}
}, H = class e {
	get _$AU() {
		return this._$AM?._$AU ?? this._$Cv;
	}
	constructor(e, t, n, r) {
		this.type = 2, this._$AH = I, this._$AN = void 0, this._$AA = e, this._$AB = t, this._$AM = n, this.options = r, this._$Cv = r?.isConnected ?? !0;
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
		e = V(this, e, t), D(e) ? e === I || e == null || e === "" ? (this._$AH !== I && this._$AR(), this._$AH = I) : e !== this._$AH && e !== F && this._(e) : e._$litType$ === void 0 ? e.nodeType === void 0 ? se(e) ? this.k(e) : this._(e) : this.T(e) : this.$(e);
	}
	O(e) {
		return this._$AA.parentNode.insertBefore(e, this._$AB);
	}
	T(e) {
		this._$AH !== e && (this._$AR(), this._$AH = this.O(e));
	}
	_(e) {
		this._$AH !== I && D(this._$AH) ? this._$AA.nextSibling.data = e : this.T(T.createTextNode(e)), this._$AH = e;
	}
	$(e) {
		let { values: t, _$litType$: n } = e, r = typeof n == "number" ? this._$AC(e) : (n.el === void 0 && (n.el = B.createElement(z(n.h, n.h[0]), this.options)), n);
		if (this._$AH?._$AD === r) this._$AH.p(t);
		else {
			let e = new fe(r, this), n = e.u(this.options);
			e.p(t), this.T(n), this._$AH = e;
		}
	}
	_$AC(e) {
		let t = L.get(e.strings);
		return t === void 0 && L.set(e.strings, t = new B(e)), t;
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
}, U = class {
	get tagName() {
		return this.element.tagName;
	}
	get _$AU() {
		return this._$AM._$AU;
	}
	constructor(e, t, n, r, i) {
		this.type = 1, this._$AH = I, this._$AN = void 0, this.element = e, this.name = t, this._$AM = r, this.options = i, n.length > 2 || n[0] !== "" || n[1] !== "" ? (this._$AH = Array(n.length - 1).fill(/* @__PURE__ */ new String()), this.strings = n) : this._$AH = I;
	}
	_$AI(e, t = this, n, r) {
		let i = this.strings, a = !1;
		if (i === void 0) e = V(this, e, t, 0), a = !D(e) || e !== this._$AH && e !== F, a && (this._$AH = e);
		else {
			let r = e, o, s;
			for (e = i[0], o = 0; o < i.length - 1; o++) s = V(this, r[n + o], t, o), s === F && (s = this._$AH[o]), a ||= !D(s) || s !== this._$AH[o], s === I ? e = I : e !== I && (e += (s ?? "") + i[o + 1]), this._$AH[o] = s;
		}
		a && !r && this.j(e);
	}
	j(e) {
		e === I ? this.element.removeAttribute(this.name) : this.element.setAttribute(this.name, e ?? "");
	}
}, pe = class extends U {
	constructor() {
		super(...arguments), this.type = 3;
	}
	j(e) {
		this.element[this.name] = e === I ? void 0 : e;
	}
}, me = class extends U {
	constructor() {
		super(...arguments), this.type = 4;
	}
	j(e) {
		this.element.toggleAttribute(this.name, !!e && e !== I);
	}
}, he = class extends U {
	constructor(e, t, n, r, i) {
		super(e, t, n, r, i), this.type = 5;
	}
	_$AI(e, t = this) {
		if ((e = V(this, e, t, 0) ?? I) === F) return;
		let n = this._$AH, r = e === I && n !== I || e.capture !== n.capture || e.once !== n.once || e.passive !== n.passive, i = e !== I && (n === I || r);
		r && this.element.removeEventListener(this.name, this, n), i && this.element.addEventListener(this.name, this, e), this._$AH = e;
	}
	handleEvent(e) {
		typeof this._$AH == "function" ? this._$AH.call(this.options?.host ?? this.element, e) : this._$AH.handleEvent(e);
	}
}, ge = class {
	constructor(e, t, n) {
		this.element = e, this.type = 6, this._$AN = void 0, this._$AM = t, this.options = n;
	}
	get _$AU() {
		return this._$AM._$AU;
	}
	_$AI(e) {
		V(this, e);
	}
}, _e = y.litHtmlPolyfillSupport;
_e?.(B, H), (y.litHtmlVersions ??= []).push("3.3.3");
var ve = (e, t, n) => {
	let r = n?.renderBefore ?? t, i = r._$litPart$;
	if (i === void 0) {
		let e = n?.renderBefore ?? null;
		r._$litPart$ = i = new H(t.insertBefore(E(), e), e, void 0, n ?? {});
	}
	return i._$AI(e), i;
}, W = globalThis, G = class extends v {
	constructor() {
		super(...arguments), this.renderOptions = { host: this }, this._$Do = void 0;
	}
	createRenderRoot() {
		let e = super.createRenderRoot();
		return this.renderOptions.renderBefore ??= e.firstChild, e;
	}
	update(e) {
		let t = this.render();
		this.hasUpdated || (this.renderOptions.isConnected = this.isConnected), super.update(e), this._$Do = ve(t, this.renderRoot, this.renderOptions);
	}
	connectedCallback() {
		super.connectedCallback(), this._$Do?.setConnected(!0);
	}
	disconnectedCallback() {
		super.disconnectedCallback(), this._$Do?.setConnected(!1);
	}
	render() {
		return F;
	}
};
G._$litElement$ = !0, G.finalized = !0, W.litElementHydrateSupport?.({ LitElement: G });
var ye = W.litElementPolyfillSupport;
ye?.({ LitElement: G }), (W.litElementVersions ??= []).push("4.2.2");
//#endregion
//#region src/helpers.ts
function be(e, t) {
	let n = e.entities?.[t]?.device_id;
	return n ? Object.values(e.entities ?? {}).filter((e) => e.device_id === n && e.entity_id.startsWith("button.")).map((t) => e.states[t.entity_id]?.state ?? "").join(",") : "";
}
function xe(e, t) {
	return t && t.length > 0 ? t.filter((t) => e.states[t]) : Object.keys(e.states).filter((e) => e.startsWith("camera.")).sort((t, n) => K(e, t).localeCompare(K(e, n)));
}
function K(e, t) {
	let n = e.states[t]?.attributes.friendly_name;
	return typeof n == "string" && n ? n : t;
}
function Se(e) {
	let t = e.trim().split(/\s+/).filter(Boolean);
	if (t.length === 0) return "?";
	let n = Array.from(t[0])[0] ?? "?";
	return (n + (/^[A-Za-z0-9]/.test(n) && t.length > 1 ? Array.from(t[1])[0] ?? "" : "")).toUpperCase();
}
function Ce(e) {
	let t = 0;
	for (let n of e) t = t * 31 + (n.codePointAt(0) ?? 0) | 0;
	return `hsl(${Math.abs(t) % 360} 55% 46%)`;
}
var q = [
	"tv",
	"cameras",
	"message",
	"apps",
	"remote",
	"media",
	"keyboard",
	"touchpad"
];
function we(e) {
	if (Array.isArray(e.sections)) {
		let t = e.sections.filter((e) => q.includes(e));
		return t.filter((e, n) => t.indexOf(e) === n);
	}
	let t = ["tv"];
	return e.show_cameras !== !1 && t.push("cameras"), e.show_message !== !1 && t.push("message"), e.show_apps !== !1 && t.push("apps"), e.show_remote !== !1 && t.push("remote", "media"), t;
}
var J = 2.5, Te = 6, Ee = 300, De = 600;
function Oe(e, t) {
	return e > Te ? "move" : t <= Ee ? "click" : t >= De ? "right" : "move";
}
//#endregion
//#region src/strings.ts
var Y = {
	en: {
		off: "Off",
		home: "Home",
		liveTv: "Live TV",
		inputList: "Inputs",
		tvCorner: "Keep Live TV / HDMI in a corner",
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
		media: "Playback and volume",
		tv: "TV and power",
		sections: "Sections (drag to reorder)",
		camerasField: "Cameras (empty: all)",
		keyboard: "Keyboard",
		touchpad: "Touchpad",
		typeHere: "Open a text field on the TV, then type here",
		send: "Send",
		leftClick: "Click",
		rightClick: "Right click",
		touchpadHint: "Drag to move · tap to click · hold for right click",
		keyboardNote: "Works with the TV's own keyboard (browser, sign-in fields). Apps with their own keyboard, like YouTube, ignore it.",
		touchpadNote: "For the web browser and apps with a pointer; elsewhere the TV shows its pointer panel instead.",
		back: "Back",
		menu: "Menu",
		ok: "OK",
		volumeDown: "Volume down",
		volumeUp: "Volume up",
		volume: "Volume",
		mute: "Mute",
		playPause: "Play / pause",
		noCameras: "No cameras in Home Assistant yet.",
		sent: "Sent to the TV",
		failed: "Failed"
	},
	ar: {
		off: "مطفأ",
		home: "الرئيسية",
		liveTv: "البث المباشر",
		inputList: "المدخلات",
		tvCorner: "إبقاء البث المباشر / HDMI في الزاوية",
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
		media: "التشغيل والصوت",
		tv: "التلفاز والتشغيل",
		sections: "الأقسام (اسحب لإعادة الترتيب)",
		camerasField: "الكاميرات (فارغ: الكل)",
		keyboard: "لوحة المفاتيح",
		touchpad: "لوحة اللمس",
		typeHere: "افتح حقل نص على التلفاز ثم اكتب هنا",
		send: "إرسال",
		leftClick: "نقر",
		rightClick: "نقر أيمن",
		touchpadHint: "اسحب للتحريك · انقر للنقر · اضغط مطولًا للنقر الأيمن",
		keyboardNote: "يعمل مع لوحة مفاتيح التلفاز (المتصفح وحقول تسجيل الدخول). التطبيقات ذات لوحة المفاتيح الخاصة مثل يوتيوب تتجاهله.",
		touchpadNote: "للمتصفح والتطبيقات التي تعرض مؤشرًا؛ في غيرها يعرض التلفاز لوحة المؤشر الخاصة به.",
		back: "رجوع",
		menu: "القائمة",
		ok: "موافق",
		volumeDown: "خفض الصوت",
		volumeUp: "رفع الصوت",
		volume: "مستوى الصوت",
		mute: "كتم",
		playPause: "تشغيل / إيقاف مؤقت",
		noCameras: "لا توجد كاميرات في Home Assistant بعد.",
		sent: "أُرسل إلى التلفاز",
		failed: "فشل"
	}
};
function X(e) {
	return e?.toLowerCase().startsWith("ar") ? "ar" : "en";
}
function ke(e) {
	return Y[e];
}
Object.keys(Y);
//#endregion
//#region src/samstream-card.ts
var Z, Ae = [
	"info",
	"warning",
	"alert"
], je = 3e3, Me = 400, Ne = 150, Pe = 600, Fe = 1.5, Ie = 16, Q = (e) => e.preventDefault(), $ = class extends G {
	constructor(...e) {
		super(...e), this.camera = "", this.feedback = "", this.severity = "info", this.held = !1, this.pending = {
			x: 0,
			y: 0
		}, this.pointerBusy = !1;
	}
	setConfig(e) {
		if (!e.entity) throw Error("Choose the Samstream TV (media player).");
		this.config = e;
	}
	getCardSize() {
		return 8;
	}
	static getConfigForm() {
		let e = (e) => ke(X(e?.locale?.language ?? e?.language));
		return {
			schema: [
				{
					name: "entity",
					required: !0,
					selector: { entity: {
						domain: "media_player",
						integration: "samstream"
					} }
				},
				{
					name: "sections",
					selector: { select: {
						multiple: !0,
						reorder: !0,
						mode: "list",
						options: q.map((t) => ({
							value: t,
							label: e()[Re(t)]
						}))
					} }
				},
				{
					name: "cameras",
					selector: { entity: {
						domain: "camera",
						multiple: !0
					} }
				}
			],
			computeLabel: (t, n) => {
				let r = e(n);
				if (t.name === "sections") return r.sections;
				if (t.name === "cameras") return r.camerasField;
			}
		};
	}
	static getStubConfig(e) {
		return {
			entity: Object.values(e.entities ?? {}).find((e) => e.platform === "samstream" && e.entity_id.startsWith("media_player."))?.entity_id ?? "",
			sections: [
				"tv",
				"cameras",
				"message",
				"apps",
				"remote",
				"media"
			]
		};
	}
	get text() {
		return ke(X(this.hass?.locale?.language ?? this.hass?.language));
	}
	get rtl() {
		return X(this.hass?.locale?.language ?? this.hass?.language) === "ar";
	}
	updated(e) {
		if (!e.has("hass") || !this.hass || !this.config) return;
		let t = `${this.hass.states[this.config.entity]?.attributes.app_id ?? null}|${be(this.hass, this.config.entity)}`;
		if ((this.apps === void 0 || t !== this.appsFor) && (this.appsFor = t, this.loadApps()), this.volumeDrag !== void 0) {
			let e = this.hass.states[this.config.entity]?.attributes.volume_level;
			typeof e == "number" && Math.round(e * 100) === this.volumeDrag && (this.volumeDrag = void 0);
		}
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
		if (!this.hass || !this.config) return I;
		let e = this.hass.states[this.config.entity];
		if (!e) return P`<ha-card><div class="empty">${this.config.entity}?</div></ha-card>`;
		let t = e.state !== "off" && e.state !== "unavailable", n = we(this.config), r = t ? n : n.includes("tv") ? ["tv"] : [];
		return P`
      <ha-card dir=${this.rtl ? "rtl" : "ltr"}>
        ${t || r.length > 0 ? I : this.renderPowerOnly()}
        ${r.map((e, n) => this.renderSection(e, t, n === 0))}
        ${this.feedback ? P`<div class="feedback">${this.feedback}</div>` : I}
      </ha-card>
    `;
	}
	renderSection(e, t, n) {
		let r = {
			tv: () => this.renderHeader(t),
			cameras: () => this.renderCameras(),
			message: () => this.renderMessage(),
			apps: () => this.renderApps(),
			remote: () => this.renderRemote(),
			media: () => this.renderMedia(),
			keyboard: () => this.renderKeyboard(),
			touchpad: () => this.renderTouchpad()
		}[e]();
		return P`<div class="section ${n ? "first" : ""}">${r}</div>`;
	}
	renderPowerOnly() {
		return P`<div class="power-only">
      <span>${K(this.hass, this.config.entity)} · ${this.text.off}</span>
      ${this.powerButton(!1)}
    </div>`;
	}
	powerButton(e) {
		return P`<button
      class="round ${e ? "on" : ""}"
      title=${this.text.power}
      @click=${() => this.call("media_player", "toggle", { entity_id: this.config.entity })}
    >
      <ha-icon icon="mdi:power"></ha-icon>
    </button>`;
	}
	renderHeader(e) {
		let t = this.text, n = this.hass.states[this.config.entity], r = n.attributes.source ?? "", i = n.attributes.app_id, a = this.apps?.apps.find((e) => e.id === i), o = e ? r === "Home" ? t.home : a?.name ?? r : t.off;
		return P`
      <div class="header">
        ${a ? this.tile(a, "small") : P`<div class="tv"><ha-icon icon="mdi:television"></ha-icon></div>`}
        <div class="titles">
          <div class="name">${K(this.hass, this.config.entity)}</div>
          <div class="sub">${o}</div>
        </div>
        ${this.powerButton(e)}
      </div>
    `;
	}
	renderCameras() {
		let e = this.text, t = xe(this.hass, this.config.cameras);
		if (t.length === 0) return P`<section><h3>${e.cameras}</h3><p class="hint">${e.noCameras}</p></section>`;
		let n = t.includes(this.camera) ? this.camera : t[0];
		return P`
      <section>
        <h3>${e.cameras}</h3>
        <div class="chips">
          ${t.map((e) => P`<button
              class="chip ${e === n ? "selected" : ""}"
              @click=${() => this.camera = e}
            >
              <ha-icon icon="mdi:cctv"></ha-icon>${K(this.hass, e)}
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
        <label class="check">
          <input id="camera-tv-corner" type="checkbox" />
          <span>${e.tvCorner}</span>
        </label>
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
		return P`
      <section>
        <h3>${e.message}</h3>
        <input id="notice-title" dir="auto" placeholder=${e.title} />
        <textarea id="notice-message" dir="auto" rows="2" placeholder=${e.messagePlaceholder}></textarea>
        <div class="row">
          <div class="chips">
            ${Ae.map((e) => P`<button
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
		return P`
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
          ${(this.apps?.sources ?? []).map((n) => P`<button
              class="app ${t.attributes.source === n ? "current" : ""}"
              @click=${() => this.selectSource(n)}
            >
              <div class="tile home">
<ha-icon icon=${Le(n)}></ha-icon>
              </div>
              <span>${n === "Live TV" ? e.liveTv : n === "Input list" ? e.inputList : n}</span>
            </button>`)}
          ${(this.apps?.apps ?? []).map((e) => P`<button
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
		let e = this.text, t = (e, t, n, r = "repeat") => {
			let i = this.pressable(() => this.sendKey(e), r, e);
			return P`<button class="key" title=${n} @pointerdown=${i.down} @pointerup=${i.up} @pointerleave=${i.cancel} @pointercancel=${i.cancel} @contextmenu=${Q}>
        <ha-icon icon=${t}></ha-icon>
      </button>`;
		}, n = this.pressable(() => this.sendKey("KEY_ENTER"), "hold", "KEY_ENTER");
		return P`
      <section>
        <h3>${e.remote}</h3>
        <div class="remote">
          <div class="pad">
            <span></span>${t("KEY_UP", "mdi:chevron-up", "▲")}<span></span>
            ${t(this.rtl ? "KEY_RIGHT" : "KEY_LEFT", this.rtl ? "mdi:chevron-right" : "mdi:chevron-left", "◀")}
            <button class="key ok" @pointerdown=${n.down} @pointerup=${n.up} @pointerleave=${n.cancel} @pointercancel=${n.cancel} @contextmenu=${Q}>
              ${e.ok}
            </button>
            ${t(this.rtl ? "KEY_LEFT" : "KEY_RIGHT", this.rtl ? "mdi:chevron-left" : "mdi:chevron-right", "▶")}
            <span></span>${t("KEY_DOWN", "mdi:chevron-down", "▼")}<span></span>
          </div>
          <div class="side">
            ${t("KEY_RETURN", "mdi:arrow-u-left-top", e.back, "hold")}
            ${t("KEY_HOME", "mdi:home", e.home, "hold")}
            ${t("KEY_MENU", "mdi:menu", e.menu, "hold")}
          </div>
        </div>
      </section>
    `;
	}
	renderMedia() {
		let e = this.text, t = (e, t, n, r = !1) => {
			let i = () => this.call("media_player", e, { entity_id: this.config.entity }, !1), a = this.pressable(i, "repeat");
			return r ? P`<button class="key" title=${n} @pointerdown=${a.down} @pointerup=${a.up} @pointerleave=${a.cancel} @pointercancel=${a.cancel} @contextmenu=${Q}>
            <ha-icon icon=${t}></ha-icon>
          </button>` : P`<button class="key" title=${n} @click=${i}><ha-icon icon=${t}></ha-icon></button>`;
		}, n = this.hass.states[this.config.entity]?.attributes.volume_level, r = typeof n == "number", i = this.volumeDrag ?? (r ? Math.round(n * 100) : 0);
		return P`
      <section>
        <h3>${e.media}</h3>
        <div class="media">
          ${t("media_play_pause", "mdi:play-pause", e.playPause)}
          <button class="key" title=${e.mute} @click=${() => this.toggleMute()}>
            <ha-icon icon="mdi:volume-off"></ha-icon>
          </button>
          <input
            class="volume"
            type="range"
            min="0"
            max="100"
            step="1"
            aria-label=${e.volume}
            .value=${String(i)}
            ?disabled=${!r}
            @input=${(e) => {
			this.volumeDrag = Number(e.target.value);
		}}
            @change=${(e) => this.setVolume(Number(e.target.value))}
          />
          <span class="level">${r || this.volumeDrag !== void 0 ? i : "–"}</span>
        </div>
      </section>
    `;
	}
	setVolume(e) {
		this.volumeDrag = Math.min(100, Math.max(0, Math.round(e))), this.call("media_player", "volume_set", {
			entity_id: this.config.entity,
			volume_level: this.volumeDrag / 100
		}, !1);
	}
	renderKeyboard() {
		let e = this.text, t = () => {
			let e = this.value("tv-text");
			if (!e) return;
			this.call("samstream", "send_text", {
				entity_id: this.config.entity,
				text: e
			});
			let t = this.renderRoot.querySelector("#tv-text");
			t && (t.value = "");
		};
		return P`
      <section>
        <h3>${e.keyboard}</h3>
        <div class="row">
          <input
            id="tv-text"
            dir="auto"
            placeholder=${e.typeHere}
            @keydown=${(e) => e.key === "Enter" && t()}
          />
          <button class="primary" @click=${t}><ha-icon icon="mdi:keyboard"></ha-icon>${e.send}</button>
        </div>
        <p class="hint">${e.keyboardNote}</p>
      </section>
    `;
	}
	renderTouchpad() {
		let e = this.text;
		return P`
      <section>
        <h3>${e.touchpad}</h3>
        <div
          class="touchpad"
          @pointerdown=${(e) => this.touchStart(e)}
          @pointermove=${(e) => this.touchMove(e)}
          @pointerup=${() => this.touchEnd()}
          @pointercancel=${() => this.touch = void 0}
          @contextmenu=${(e) => e.preventDefault()}
        >
          <span>${e.touchpadHint}</span>
        </div>
        <div class="actions">
          <button @click=${() => this.pointer({ click: "left" })}>
            <ha-icon icon="mdi:cursor-default-click"></ha-icon>${e.leftClick}
          </button>
          <button @click=${() => this.pointer({ click: "right" })}>
            <ha-icon icon="mdi:mouse-right-click"></ha-icon>${e.rightClick}
          </button>
        </div>
        <p class="hint">${e.touchpadNote}</p>
      </section>
    `;
	}
	pressable(e, t, n) {
		let r = () => {
			clearTimeout(this.holdTimer), clearInterval(this.repeatTimer);
		};
		return {
			down: (i) => {
				i.currentTarget.setPointerCapture?.(i.pointerId), r(), this.held = !1, t === "repeat" ? (e(), this.holdTimer = setTimeout(() => {
					this.repeatTimer = setInterval(e, Ne);
				}, Me)) : this.holdTimer = setTimeout(() => {
					this.held = !0, n && this.call("samstream", "hold_key", {
						entity_id: this.config.entity,
						key: n,
						seconds: Fe
					}, !1);
				}, Pe);
			},
			up: () => {
				r(), t === "hold" && !this.held && e(), this.held = !1;
			},
			cancel: () => {
				r(), this.held = !1;
			}
		};
	}
	touchStart(e) {
		e.currentTarget.setPointerCapture?.(e.pointerId), this.touch = {
			x: e.clientX,
			y: e.clientY,
			at: Date.now(),
			travel: 0
		};
	}
	touchMove(e) {
		let t = this.touch;
		if (!t) return;
		let n = e.clientX - t.x, r = e.clientY - t.y;
		t.x = e.clientX, t.y = e.clientY, t.travel += Math.abs(n) + Math.abs(r), this.pending.x += n * J, this.pending.y += r * J, !this.flushTimer && !this.pointerBusy && (this.flushTimer = setTimeout(() => this.flushPointer(), Ie));
	}
	touchEnd() {
		let e = this.touch;
		if (this.touch = void 0, !e) return;
		let t = Oe(e.travel, Date.now() - e.at);
		t === "click" ? this.pointer({ click: "left" }) : t === "right" && this.pointer({ click: "right" });
	}
	flushPointer() {
		this.flushTimer = void 0;
		let e = Math.round(this.pending.x), t = Math.round(this.pending.y);
		this.pointerBusy || !e && !t || (this.pending = {
			x: this.pending.x - e,
			y: this.pending.y - t
		}, this.pointerBusy = !0, this.hass.callService("samstream", "pointer", {
			entity_id: this.config.entity,
			move_x: e,
			move_y: t
		}).catch(() => void 0).finally(() => {
			this.pointerBusy = !1, this.flushPointer();
		}));
	}
	pointer(e) {
		this.call("samstream", "pointer", {
			entity_id: this.config.entity,
			...e
		}, !1);
	}
	tile(e, t) {
		return e.logo ? P`<div class="tile ${t}"><img src=${e.logo} alt="" loading="lazy" /></div>` : P`<div class="tile ${t} letter" style="background:${Ce(e.name)}">
      ${Se(e.name)}
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
		let t = this.value("camera-message"), n = this.duration("camera-duration"), r = this.renderRoot.querySelector("#camera-tv-corner")?.checked;
		this.call("samstream", "play_stream", {
			entity_id: this.config.entity,
			camera: e,
			...t ? { message: t } : {},
			...n ? { duration: n } : {},
			...r ? { tv_corner: "on" } : {}
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
		this.call("samstream", "send_keys", {
			entity_id: this.config.entity,
			keys: [e]
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
		this.feedback = e, clearTimeout(this.feedbackTimer), this.feedbackTimer = setTimeout(() => this.feedback = "", je);
	}
};
Z = $, Z.properties = {
	hass: { attribute: !1 },
	config: { state: !0 },
	apps: { state: !0 },
	camera: { state: !0 },
	feedback: { state: !0 },
	severity: { state: !0 },
	volumeDrag: { state: !0 }
}, Z.styles = o`
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
    }
    .section:not(.first) {
      padding-top: 14px;
      border-top: 1px solid var(--divider-color);
    }
    .power-only {
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: 12px;
      color: var(--secondary-text-color);
    }
    .media {
      display: flex;
      align-items: center;
      gap: 8px;
    }
    .media .spacer {
      flex: 1;
    }
    .media .volume {
      flex: 1;
      min-width: 0;
      accent-color: var(--primary-color);
      cursor: pointer;
    }
    .media .volume:disabled {
      cursor: default;
      opacity: 0.4;
    }
    .media .level {
      min-width: 2.5em;
      text-align: center;
      font-variant-numeric: tabular-nums;
      color: var(--secondary-text-color);
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
    .touchpad {
      height: 180px;
      border-radius: 14px;
      background: var(--secondary-background-color);
      display: flex;
      align-items: flex-end;
      justify-content: center;
      padding: 10px;
      box-sizing: border-box;
      touch-action: none;
      user-select: none;
      -webkit-user-select: none;
      cursor: crosshair;
    }
    .touchpad span {
      font-size: 0.78rem;
      color: var(--secondary-text-color);
      text-align: center;
    }
    .key {
      touch-action: manipulation;
      user-select: none;
      -webkit-user-select: none;
    }
    .check {
      display: flex;
      align-items: center;
      gap: 8px;
      color: var(--secondary-text-color);
      cursor: pointer;
    }
    .check input {
      width: auto;
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
  `;
function Le(e) {
	return e.startsWith("HDMI") ? "mdi:video-input-hdmi" : e === "Input list" ? "mdi:import" : "mdi:television-classic";
}
function Re(e) {
	return e;
}
customElements.get("samstream-card") || (customElements.define("samstream-card", $), (window.customCards ??= []).push({
	type: "samstream-card",
	name: "Samstream",
	description: "Cameras, messages, apps and a remote for your Samsung TV.",
	preview: !0,
	documentationURL: "https://github.com/Mrslimon/samstream"
}));
//#endregion
export { $ as SamstreamCard };
