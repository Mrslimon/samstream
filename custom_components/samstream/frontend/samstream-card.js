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
}, ae = (e, t) => !l(e, t), oe = {
	attribute: !0,
	type: String,
	converter: h,
	reflect: !1,
	useDefault: !1,
	hasChanged: ae
};
Symbol.metadata ??= Symbol("metadata"), f.litPropertyMetadata ??= /* @__PURE__ */ new WeakMap();
var g = class extends HTMLElement {
	static addInitializer(e) {
		this._$Ei(), (this.l ??= []).push(e);
	}
	static get observedAttributes() {
		return this.finalize(), this._$Eh && [...this._$Eh.keys()];
	}
	static createProperty(e, t = oe) {
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
		return this.elementProperties.get(e) ?? oe;
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
			if (!1 === r && (i = this[e]), n ??= a.getPropertyOptions(e), !((n.hasChanged ?? ae)(i, t) || n.useDefault && n.reflect && i === this._$Ej?.get(e) && !this.hasAttribute(a._$Eu(e, n)))) return;
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
g.elementStyles = [], g.shadowRootOptions = { mode: "open" }, g[m("elementProperties")] = /* @__PURE__ */ new Map(), g[m("finalized")] = /* @__PURE__ */ new Map(), ie?.({ ReactiveElement: g }), (f.reactiveElementVersions ??= []).push("2.1.2");
//#endregion
//#region node_modules/lit-html/lit-html.js
var _ = globalThis, se = (e) => e, v = _.trustedTypes, y = v ? v.createPolicy("lit-html", { createHTML: (e) => e }) : void 0, b = "$lit$", x = `lit$${Math.random().toFixed(9).slice(2)}$`, ce = "?" + x, le = `<${ce}>`, S = document, C = () => S.createComment(""), w = (e) => e === null || typeof e != "object" && typeof e != "function", T = Array.isArray, ue = (e) => T(e) || typeof e?.[Symbol.iterator] == "function", E = "[ 	\n\f\r]", D = /<(?:(!--|\/[^a-zA-Z])|(\/?[a-zA-Z][^>\s]*)|(\/?$))/g, O = /-->/g, de = />/g, k = RegExp(`>|${E}(?:([^\\s"'>=/]+)(${E}*=${E}*(?:[^ \t\n\f\r"'\`<>=]|("|')|))|$)`, "g"), A = /'/g, j = /"/g, fe = /^(?:script|style|textarea|title)$/i, M = ((e) => (t, ...n) => ({
	_$litType$: e,
	strings: t,
	values: n
}))(1), N = Symbol.for("lit-noChange"), P = Symbol.for("lit-nothing"), pe = /* @__PURE__ */ new WeakMap(), F = S.createTreeWalker(S, 129);
function me(e, t) {
	if (!T(e) || !e.hasOwnProperty("raw")) throw Error("invalid template strings array");
	return y === void 0 ? t : y.createHTML(t);
}
var he = (e, t) => {
	let n = e.length - 1, r = [], i, a = t === 2 ? "<svg>" : t === 3 ? "<math>" : "", o = D;
	for (let t = 0; t < n; t++) {
		let n = e[t], s, c, l = -1, u = 0;
		for (; u < n.length && (o.lastIndex = u, c = o.exec(n), c !== null);) u = o.lastIndex, o === D ? c[1] === "!--" ? o = O : c[1] === void 0 ? c[2] === void 0 ? c[3] !== void 0 && (o = k) : (fe.test(c[2]) && (i = RegExp("</" + c[2], "g")), o = k) : o = de : o === k ? c[0] === ">" ? (o = i ?? D, l = -1) : c[1] === void 0 ? l = -2 : (l = o.lastIndex - c[2].length, s = c[1], o = c[3] === void 0 ? k : c[3] === "\"" ? j : A) : o === j || o === A ? o = k : o === O || o === de ? o = D : (o = k, i = void 0);
		let d = o === k && e[t + 1].startsWith("/>") ? " " : "";
		a += o === D ? n + le : l >= 0 ? (r.push(s), n.slice(0, l) + b + n.slice(l) + x + d) : n + x + (l === -2 ? t : d);
	}
	return [me(e, a + (e[n] || "<?>") + (t === 2 ? "</svg>" : t === 3 ? "</math>" : "")), r];
}, I = class e {
	constructor({ strings: t, _$litType$: n }, r) {
		let i;
		this.parts = [];
		let a = 0, o = 0, s = t.length - 1, c = this.parts, [l, u] = he(t, n);
		if (this.el = e.createElement(l, r), F.currentNode = this.el.content, n === 2 || n === 3) {
			let e = this.el.content.firstChild;
			e.replaceWith(...e.childNodes);
		}
		for (; (i = F.nextNode()) !== null && c.length < s;) {
			if (i.nodeType === 1) {
				if (i.hasAttributes()) for (let e of i.getAttributeNames()) if (e.endsWith(b)) {
					let t = u[o++], n = i.getAttribute(e).split(x), r = /([.?@])?(.*)/.exec(t);
					c.push({
						type: 1,
						index: a,
						name: r[2],
						strings: n,
						ctor: r[1] === "." ? _e : r[1] === "?" ? ve : r[1] === "@" ? ye : z
					}), i.removeAttribute(e);
				} else e.startsWith(x) && (c.push({
					type: 6,
					index: a
				}), i.removeAttribute(e));
				if (fe.test(i.tagName)) {
					let e = i.textContent.split(x), t = e.length - 1;
					if (t > 0) {
						i.textContent = v ? v.emptyScript : "";
						for (let n = 0; n < t; n++) i.append(e[n], C()), F.nextNode(), c.push({
							type: 2,
							index: ++a
						});
						i.append(e[t], C());
					}
				}
			} else if (i.nodeType === 8) {
				if (i.data === ce) c.push({
					type: 2,
					index: a
				});
				else {
					let e = -1;
					for (; (e = i.data.indexOf(x, e + 1)) !== -1;) c.push({
						type: 7,
						index: a
					}), e += x.length - 1;
				}
			}
			a++;
		}
	}
	static createElement(e, t) {
		let n = S.createElement("template");
		return n.innerHTML = e, n;
	}
};
function L(e, t, n = e, r) {
	if (t === N) return t;
	let i = r === void 0 ? n._$Cl : n._$Co?.[r], a = w(t) ? void 0 : t._$litDirective$;
	return i?.constructor !== a && (i?._$AO?.(!1), a === void 0 ? i = void 0 : (i = new a(e), i._$AT(e, n, r)), r === void 0 ? n._$Cl = i : (n._$Co ??= [])[r] = i), i !== void 0 && (t = L(e, i._$AS(e, t.values), i, r)), t;
}
var ge = class {
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
		let { el: { content: t }, parts: n } = this._$AD, r = (e?.creationScope ?? S).importNode(t, !0);
		F.currentNode = r;
		let i = F.nextNode(), a = 0, o = 0, s = n[0];
		for (; s !== void 0;) {
			if (a === s.index) {
				let t;
				s.type === 2 ? t = new R(i, i.nextSibling, this, e) : s.type === 1 ? t = new s.ctor(i, s.name, s.strings, this, e) : s.type === 6 && (t = new be(i, this, e)), this._$AV.push(t), s = n[++o];
			}
			a !== s?.index && (i = F.nextNode(), a++);
		}
		return F.currentNode = S, r;
	}
	p(e) {
		let t = 0;
		for (let n of this._$AV) n !== void 0 && (n.strings === void 0 ? n._$AI(e[t]) : (n._$AI(e, n, t), t += n.strings.length - 2)), t++;
	}
}, R = class e {
	get _$AU() {
		return this._$AM?._$AU ?? this._$Cv;
	}
	constructor(e, t, n, r) {
		this.type = 2, this._$AH = P, this._$AN = void 0, this._$AA = e, this._$AB = t, this._$AM = n, this.options = r, this._$Cv = r?.isConnected ?? !0;
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
		e = L(this, e, t), w(e) ? e === P || e == null || e === "" ? (this._$AH !== P && this._$AR(), this._$AH = P) : e !== this._$AH && e !== N && this._(e) : e._$litType$ === void 0 ? e.nodeType === void 0 ? ue(e) ? this.k(e) : this._(e) : this.T(e) : this.$(e);
	}
	O(e) {
		return this._$AA.parentNode.insertBefore(e, this._$AB);
	}
	T(e) {
		this._$AH !== e && (this._$AR(), this._$AH = this.O(e));
	}
	_(e) {
		this._$AH !== P && w(this._$AH) ? this._$AA.nextSibling.data = e : this.T(S.createTextNode(e)), this._$AH = e;
	}
	$(e) {
		let { values: t, _$litType$: n } = e, r = typeof n == "number" ? this._$AC(e) : (n.el === void 0 && (n.el = I.createElement(me(n.h, n.h[0]), this.options)), n);
		if (this._$AH?._$AD === r) this._$AH.p(t);
		else {
			let e = new ge(r, this), n = e.u(this.options);
			e.p(t), this.T(n), this._$AH = e;
		}
	}
	_$AC(e) {
		let t = pe.get(e.strings);
		return t === void 0 && pe.set(e.strings, t = new I(e)), t;
	}
	k(t) {
		T(this._$AH) || (this._$AH = [], this._$AR());
		let n = this._$AH, r, i = 0;
		for (let a of t) i === n.length ? n.push(r = new e(this.O(C()), this.O(C()), this, this.options)) : r = n[i], r._$AI(a), i++;
		i < n.length && (this._$AR(r && r._$AB.nextSibling, i), n.length = i);
	}
	_$AR(e = this._$AA.nextSibling, t) {
		for (this._$AP?.(!1, !0, t); e !== this._$AB;) {
			let t = se(e).nextSibling;
			se(e).remove(), e = t;
		}
	}
	setConnected(e) {
		this._$AM === void 0 && (this._$Cv = e, this._$AP?.(e));
	}
}, z = class {
	get tagName() {
		return this.element.tagName;
	}
	get _$AU() {
		return this._$AM._$AU;
	}
	constructor(e, t, n, r, i) {
		this.type = 1, this._$AH = P, this._$AN = void 0, this.element = e, this.name = t, this._$AM = r, this.options = i, n.length > 2 || n[0] !== "" || n[1] !== "" ? (this._$AH = Array(n.length - 1).fill(/* @__PURE__ */ new String()), this.strings = n) : this._$AH = P;
	}
	_$AI(e, t = this, n, r) {
		let i = this.strings, a = !1;
		if (i === void 0) e = L(this, e, t, 0), a = !w(e) || e !== this._$AH && e !== N, a && (this._$AH = e);
		else {
			let r = e, o, s;
			for (e = i[0], o = 0; o < i.length - 1; o++) s = L(this, r[n + o], t, o), s === N && (s = this._$AH[o]), a ||= !w(s) || s !== this._$AH[o], s === P ? e = P : e !== P && (e += (s ?? "") + i[o + 1]), this._$AH[o] = s;
		}
		a && !r && this.j(e);
	}
	j(e) {
		e === P ? this.element.removeAttribute(this.name) : this.element.setAttribute(this.name, e ?? "");
	}
}, _e = class extends z {
	constructor() {
		super(...arguments), this.type = 3;
	}
	j(e) {
		this.element[this.name] = e === P ? void 0 : e;
	}
}, ve = class extends z {
	constructor() {
		super(...arguments), this.type = 4;
	}
	j(e) {
		this.element.toggleAttribute(this.name, !!e && e !== P);
	}
}, ye = class extends z {
	constructor(e, t, n, r, i) {
		super(e, t, n, r, i), this.type = 5;
	}
	_$AI(e, t = this) {
		if ((e = L(this, e, t, 0) ?? P) === N) return;
		let n = this._$AH, r = e === P && n !== P || e.capture !== n.capture || e.once !== n.once || e.passive !== n.passive, i = e !== P && (n === P || r);
		r && this.element.removeEventListener(this.name, this, n), i && this.element.addEventListener(this.name, this, e), this._$AH = e;
	}
	handleEvent(e) {
		typeof this._$AH == "function" ? this._$AH.call(this.options?.host ?? this.element, e) : this._$AH.handleEvent(e);
	}
}, be = class {
	constructor(e, t, n) {
		this.element = e, this.type = 6, this._$AN = void 0, this._$AM = t, this.options = n;
	}
	get _$AU() {
		return this._$AM._$AU;
	}
	_$AI(e) {
		L(this, e);
	}
}, xe = _.litHtmlPolyfillSupport;
xe?.(I, R), (_.litHtmlVersions ??= []).push("3.3.3");
var Se = (e, t, n) => {
	let r = n?.renderBefore ?? t, i = r._$litPart$;
	if (i === void 0) {
		let e = n?.renderBefore ?? null;
		r._$litPart$ = i = new R(t.insertBefore(C(), e), e, void 0, n ?? {});
	}
	return i._$AI(e), i;
}, B = globalThis, V = class extends g {
	constructor() {
		super(...arguments), this.renderOptions = { host: this }, this._$Do = void 0;
	}
	createRenderRoot() {
		let e = super.createRenderRoot();
		return this.renderOptions.renderBefore ??= e.firstChild, e;
	}
	update(e) {
		let t = this.render();
		this.hasUpdated || (this.renderOptions.isConnected = this.isConnected), super.update(e), this._$Do = Se(t, this.renderRoot, this.renderOptions);
	}
	connectedCallback() {
		super.connectedCallback(), this._$Do?.setConnected(!0);
	}
	disconnectedCallback() {
		super.disconnectedCallback(), this._$Do?.setConnected(!1);
	}
	render() {
		return N;
	}
};
V._$litElement$ = !0, V.finalized = !0, B.litElementHydrateSupport?.({ LitElement: V });
var Ce = B.litElementPolyfillSupport;
Ce?.({ LitElement: V }), (B.litElementVersions ??= []).push("4.2.2");
//#endregion
//#region src/helpers.ts
function we(e, t) {
	let n = e.entities?.[t]?.device_id;
	return n ? Object.values(e.entities ?? {}).filter((e) => e.device_id === n && e.entity_id.startsWith("button.")).map((t) => e.states[t.entity_id]?.state ?? "").join(",") : "";
}
function Te(e, t) {
	return t && t.length > 0 ? t.filter((t) => e.states[t]) : Object.keys(e.states).filter((e) => e.startsWith("camera.")).sort((t, n) => H(e, t).localeCompare(H(e, n)));
}
function H(e, t) {
	let n = e.states[t]?.attributes.friendly_name;
	return typeof n == "string" && n ? n : t;
}
function Ee(e) {
	let t = e.trim().split(/\s+/).filter(Boolean);
	if (t.length === 0) return "?";
	let n = Array.from(t[0])[0] ?? "?";
	return (n + (/^[A-Za-z0-9]/.test(n) && t.length > 1 ? Array.from(t[1])[0] ?? "" : "")).toUpperCase();
}
function De(e) {
	let t = 0;
	for (let n of e) t = t * 31 + (n.codePointAt(0) ?? 0) | 0;
	return `hsl(${Math.abs(t) % 360} 55% 46%)`;
}
var U = [
	"tv",
	"cameras",
	"message",
	"apps",
	"remote",
	"media",
	"keyboard",
	"touchpad",
	"art"
];
function Oe(e) {
	if (Array.isArray(e.sections)) {
		let t = e.sections.filter((e) => U.includes(e));
		return t.filter((e, n) => t.indexOf(e) === n);
	}
	let t = ["tv"];
	return e.show_cameras !== !1 && t.push("cameras"), e.show_message !== !1 && t.push("message"), e.show_apps !== !1 && t.push("apps"), e.show_remote !== !1 && t.push("remote", "media"), t.push("art"), t;
}
var W = 2.5, ke = 6, Ae = 300, je = 600;
function Me(e, t) {
	return e > ke ? "move" : t <= Ae ? "click" : t >= je ? "right" : "move";
}
//#endregion
//#region src/strings.ts
var G = {
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
		failed: "Failed",
		art: "Art",
		artUpload: "Add picture",
		artBorder: "Frame border",
		artNoBorder: "None",
		artApply: "Apply border",
		artCropHint: "Drag to choose the part to show; zoom in for less. The dimmed part will not be on the TV.",
		artSharp: "Sharp on the 4K screen",
		artFine: "Fine, slightly enlarged",
		artSoft: "Low resolution: it will look soft",
		artOnTv: "On the TV",
		artCancel: "Cancel",
		artUploadShow: "Upload and show",
		artUploading: "Uploading…",
		artUploaded: "Added to My Photos and shown on the TV",
		artFailed: "Could not reach the Frame's art gallery",
		artNotPicture: "That file is not a picture this browser can open"
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
		failed: "فشل",
		art: "الفن",
		artUpload: "إضافة صورة",
		artBorder: "إطار الصورة",
		artNoBorder: "بلا إطار",
		artApply: "تطبيق الإطار",
		artCropHint: "اسحب لاختيار الجزء الذي يظهر، وكبّر لإظهار جزء أصغر. الجزء المعتم لن يظهر على التلفاز.",
		artSharp: "واضحة على شاشة 4K",
		artFine: "جيدة، مكبّرة قليلًا",
		artSoft: "دقة منخفضة: ستبدو غير حادة",
		artOnTv: "على التلفاز",
		artCancel: "إلغاء",
		artUploadShow: "رفع وعرض",
		artUploading: "جارٍ الرفع…",
		artUploaded: "أُضيفت إلى صوري وعُرضت على التلفاز",
		artFailed: "تعذّر الوصول إلى معرض الفن في Frame",
		artNotPicture: "هذا الملف ليس صورة يستطيع المتصفح فتحها"
	}
};
function K(e) {
	return e?.toLowerCase().startsWith("ar") ? "ar" : "en";
}
function Ne(e) {
	return G[e];
}
Object.keys(G);
//#endregion
//#region src/art-helpers.ts
var q = {
	width: 3840,
	height: 2160
}, J = q.width / q.height;
function Pe(e, t) {
	let n = Math.min(e, t * J), r = n / J;
	return {
		x: (e - n) / 2,
		y: (t - r) / 2,
		width: n,
		height: r
	};
}
function Fe(e, t, n) {
	return {
		...e,
		x: Math.min(Math.max(e.x, 0), t - e.width),
		y: Math.min(Math.max(e.y, 0), n - e.height)
	};
}
function Ie(e, t, n, r) {
	let i = Pe(t, n), a = Math.min(Math.max(r, 1), 4), o = i.width / a, s = o / J, c = e.x + e.width / 2, l = e.y + e.height / 2;
	return Fe({
		x: c - o / 2,
		y: l - s / 2,
		width: o,
		height: s
	}, t, n);
}
function Le(e, t, n, r, i) {
	return Fe({
		...e,
		x: e.x + t,
		y: e.y + n
	}, r, i);
}
function Re(e) {
	return e.width >= q.width * .95 ? "sharp" : e.width >= q.width / 2 ? "fine" : "soft";
}
function Y(e, t) {
	return e === "none" || !t ? "none" : `${e}_${t}`;
}
function ze(e) {
	if (!e || e === "none") return {
		style: "none",
		colour: ""
	};
	let t = e.lastIndexOf("_");
	return t < 0 ? {
		style: e,
		colour: ""
	} : {
		style: e.slice(0, t),
		colour: e.slice(t + 1)
	};
}
var Be = {
	none: 0,
	modernthin: .04,
	modern: .07,
	modernwide: .1,
	flexible: .07,
	shadowbox: .08,
	panoramic: .1,
	triptych: .08,
	mix: .07,
	squares: .07
};
function Ve(e) {
	return Be[e] ?? .07;
}
function He(e) {
	return e ? `rgb(${e[0]}, ${e[1]}, ${e[2]})` : "transparent";
}
function Ue(e, t, n) {
	let r = new URLSearchParams({ matte: t });
	return n && r.set("show", "1"), `${e}?${r.toString()}`;
}
//#endregion
//#region src/art.ts
var X, We = .92, Ge = class extends V {
	constructor(...e) {
		super(...e), this.entity = "", this.busy = !1, this.note = "", this.loadedFor = "", this.pick = async (e) => {
			let t = e.target, n = t.files?.[0];
			if (t.value = "", !n) return;
			let r = URL.createObjectURL(n), i = new Image();
			i.src = r;
			try {
				await i.decode();
			} catch {
				URL.revokeObjectURL(r), this.note = this.text.artNotPicture;
				return;
			}
			this.editor && URL.revokeObjectURL(this.editor.url), this.note = "", this.editor = {
				image: i,
				url: r,
				crop: Pe(i.naturalWidth, i.naturalHeight),
				zoom: 1,
				style: "none",
				colour: ""
			};
		}, this.close = () => {
			this.editor && URL.revokeObjectURL(this.editor.url), this.editor = void 0;
		}, this.zoomTo = (e) => {
			let t = this.editor;
			if (!t) return;
			let n = Number(e.target.value), { naturalWidth: r, naturalHeight: i } = t.image;
			this.editor = {
				...t,
				zoom: n,
				crop: Ie(t.crop, r, i, n)
			};
		}, this.dragStart = (e) => {
			e.target.setPointerCapture(e.pointerId), this.drag = {
				x: e.clientX,
				y: e.clientY
			};
		}, this.dragMove = (e) => {
			let t = this.editor;
			if (!this.drag || !t) return;
			let n = e.target, r = t.image.naturalWidth / n.clientWidth, i = (e.clientX - this.drag.x) * r, a = (e.clientY - this.drag.y) * r;
			this.drag = {
				x: e.clientX,
				y: e.clientY
			};
			let { naturalWidth: o, naturalHeight: s } = t.image;
			this.editor = {
				...t,
				crop: Le(t.crop, i, a, o, s)
			};
		}, this.dragEnd = () => {
			this.drag = void 0;
		}, this.upload = async () => {
			let e = this.editor, t = this.listing;
			if (e && t && this.hass.fetchWithAuth) {
				this.busy = !0, this.note = "";
				try {
					let n = document.createElement("canvas");
					n.width = q.width, n.height = q.height;
					let r = n.getContext("2d");
					if (!r) throw Error("no canvas");
					r.imageSmoothingQuality = "high";
					let { crop: i } = e;
					r.drawImage(e.image, i.x, i.y, i.width, i.height, 0, 0, q.width, q.height);
					let a = await new Promise((e) => n.toBlob(e, "image/jpeg", We));
					if (!a) throw Error("no picture");
					let o = Y(e.style, e.colour), s = await this.hass.fetchWithAuth(Ue(t.upload_url, o, !0), {
						method: "POST",
						headers: { "Content-Type": "image/jpeg" },
						body: a
					});
					if (!s.ok) throw Error(String(s.status));
					this.close(), this.note = this.text.artUploaded, await this.load();
				} catch {
					this.note = this.text.artFailed;
				} finally {
					this.busy = !1;
				}
			}
		};
	}
	updated(e) {
		e.has("entity") && this.entity && this.entity !== this.loadedFor && (this.loadedFor = this.entity, this.load()), this.editor && this.draw();
	}
	disconnectedCallback() {
		super.disconnectedCallback(), this.editor && URL.revokeObjectURL(this.editor.url);
	}
	async load() {
		try {
			let e = await this.hass.callWS({
				type: "call_service",
				domain: "samstream",
				service: "list_art",
				service_data: {},
				target: { entity_id: this.entity },
				return_response: !0
			});
			this.listing = e.response[this.entity], this.border = void 0;
		} catch {
			this.note = this.text.artFailed;
		}
	}
	render() {
		let e = this.text;
		return M`
      <section>
        <div class="row">
          <h3>${e.art}</h3>
          <label class="upload">
            <ha-icon icon="mdi:image-plus"></ha-icon>${e.artUpload}
            <input type="file" accept="image/jpeg,image/png" @change=${this.pick} hidden />
          </label>
        </div>
        ${this.editor ? this.renderEditor(this.editor) : this.renderGallery()}
        ${this.note ? M`<p class="hint">${this.note}</p>` : P}
      </section>
    `;
	}
	renderGallery() {
		let e = this.listing;
		if (!e) return M`<p class="hint">…</p>`;
		let t = e.art.find((t) => t.content_id === e.current);
		return M`
      <div class="grid">
        ${e.art.map((t) => M`<button
            class="thumb ${t.content_id === e.current ? "current" : ""}"
            title=${t.content_id}
            @click=${() => this.show(t.content_id)}
          >
            <span class="name">${t.content_id}</span>
            <img
              src=${t.thumbnail}
              alt=${t.content_id}
              loading="lazy"
              @error=${(e) => e.target.style.visibility = "hidden"}
            />
          </button>`)}
      </div>
      ${t ? this.renderBorder(t.content_id, t.matte_id) : P}
    `;
	}
	renderBorder(e, t) {
		let n = this.text, r = this.border ?? ze(t), i = Y(r.style, r.colour) !== (t ?? "none");
		return M`
      <div class="border">
        <span class="label">${n.artBorder}</span>
        ${this.matteChoices(r, (e, t) => this.border = {
			style: e,
			colour: t
		})}
        <button
          class="primary"
          ?disabled=${!i || this.busy}
          @click=${() => this.show(e, Y(r.style, r.colour))}
        >
          ${n.artApply}
        </button>
      </div>
    `;
	}
	matteChoices(e, t) {
		let n = this.listing?.mattes ?? {
			styles: ["none"],
			colours: {}
		}, r = Object.keys(n.colours), i = e.colour || r[0] || "";
		return M`
      <div class="chips">
        ${n.styles.map((n) => M`<button
            class="chip ${n === e.style ? "selected" : ""}"
            @click=${() => t(n, i)}
          >
            ${n === "none" ? this.text.artNoBorder : n}
          </button>`)}
      </div>
      ${e.style === "none" ? P : M`<div class="swatches">
            ${r.map((r) => M`<button
                class="swatch ${r === i ? "selected" : ""}"
                title=${r}
                style="background:${He(n.colours[r])}"
                @click=${() => t(e.style, r)}
              ></button>`)}
          </div>`}
    `;
	}
	renderEditor(e) {
		let t = this.text, n = Re(e.crop), r = `${Math.round(e.crop.width)}×${Math.round(e.crop.height)}`;
		return M`
      <p class="hint">${t.artCropHint}</p>
      <canvas
        class="source"
        @pointerdown=${this.dragStart}
        @pointermove=${this.dragMove}
        @pointerup=${this.dragEnd}
        @pointercancel=${this.dragEnd}
      ></canvas>
      <label class="zoom">
        <ha-icon icon="mdi:magnify-plus-outline"></ha-icon>
        <input
          type="range"
          min="1"
          max=${4}
          step="0.01"
          .value=${String(e.zoom)}
          @input=${this.zoomTo}
        />
      </label>
      <div class="quality ${n}">
        ${n === "sharp" ? t.artSharp : n === "fine" ? t.artFine : t.artSoft}
        <span class="size">${r} → ${q.width}×${q.height}</span>
      </div>
      <h4>${t.artOnTv}</h4>
      <canvas class="preview"></canvas>
      <span class="label">${t.artBorder}</span>
      ${this.matteChoices(e, (t, n) => this.editor = {
			...e,
			style: t,
			colour: n
		})}
      <div class="actions">
        <button @click=${this.close} ?disabled=${this.busy}>${t.artCancel}</button>
        <button class="primary" @click=${this.upload} ?disabled=${this.busy}>
          ${this.busy ? t.artUploading : t.artUploadShow}
        </button>
      </div>
    `;
	}
	draw() {
		let e = this.editor, t = this.renderRoot.querySelector("canvas.source"), n = this.renderRoot.querySelector("canvas.preview");
		if (!e || !t || !n) return;
		let { image: r, crop: i } = e, a = t.clientWidth || 320, o = a / r.naturalWidth;
		t.width = a * devicePixelRatio, t.height = r.naturalHeight * o * devicePixelRatio, t.style.height = `${r.naturalHeight * o}px`;
		let s = t.getContext("2d");
		if (s) {
			s.setTransform(o * devicePixelRatio, 0, 0, o * devicePixelRatio, 0, 0), s.drawImage(r, 0, 0), s.fillStyle = "rgba(0, 0, 0, 0.6)";
			let { x: e, y: t, width: n, height: a } = i, c = r.naturalWidth, l = r.naturalHeight;
			s.fillRect(0, 0, c, t), s.fillRect(0, t + a, c, l - t - a), s.fillRect(0, t, e, a), s.fillRect(e + n, t, c - e - n, a), s.strokeStyle = "white", s.lineWidth = 2 / o, s.strokeRect(e, t, n, a), s.globalAlpha = .35;
			for (let r of [1, 2]) s.beginPath(), s.moveTo(e + n * r / 3, t), s.lineTo(e + n * r / 3, t + a), s.moveTo(e, t + a * r / 3), s.lineTo(e + n, t + a * r / 3), s.stroke();
			s.globalAlpha = 1;
		}
		this.drawScreen(n, n.clientWidth || 320, e);
	}
	drawScreen(e, t, n) {
		let r = t / (q.width / q.height);
		e.width = t * devicePixelRatio, e.height = r * devicePixelRatio, e.style.height = `${r}px`;
		let i = e.getContext("2d");
		if (!i) return;
		i.setTransform(devicePixelRatio, 0, 0, devicePixelRatio, 0, 0);
		let a = n.style === "none" ? 0 : Ve(n.style) * t;
		a && (i.fillStyle = He(this.listing?.mattes.colours[n.colour]), i.fillRect(0, 0, t, r));
		let { crop: o, image: s } = n;
		i.drawImage(s, o.x, o.y, o.width, o.height, a, a, t - 2 * a, r - 2 * a);
	}
	async show(e, t) {
		this.busy = !0;
		try {
			await this.hass.callService("samstream", "select_art", {
				entity_id: this.entity,
				content_id: e,
				...t ? { matte: t } : {}
			}), this.listing &&= {
				...this.listing,
				current: e
			}, t && await this.load();
		} catch {
			this.note = this.text.artFailed;
		} finally {
			this.busy = !1;
		}
	}
};
X = Ge, X.properties = {
	hass: { attribute: !1 },
	entity: { type: String },
	text: { attribute: !1 },
	listing: { state: !0 },
	editor: { state: !0 },
	busy: { state: !0 },
	note: { state: !0 },
	border: { state: !0 }
}, X.styles = o`
    h3,
    h4 {
      margin: 0;
      font-size: 0.95rem;
      font-weight: 500;
    }
    h4 {
      margin-top: 12px;
      color: var(--secondary-text-color);
    }
    .row {
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: 8px;
      margin-bottom: 8px;
    }
    .upload {
      display: inline-flex;
      align-items: center;
      gap: 6px;
      cursor: pointer;
      color: var(--primary-color);
    }
    .grid {
      display: grid;
      grid-template-columns: repeat(auto-fill, minmax(96px, 1fr));
      gap: 6px;
    }
    .thumb {
      padding: 0;
      border: 2px solid transparent;
      border-radius: 6px;
      overflow: hidden;
      background: var(--secondary-background-color);
      cursor: pointer;
      aspect-ratio: 16 / 9;
      position: relative;
    }
    /* Shown when the TV has no thumbnail (some store artwork). */
    .thumb .name {
      position: absolute;
      inset: 0;
      display: flex;
      align-items: center;
      justify-content: center;
      font-size: 11px;
      color: var(--secondary-text-color);
    }
    .thumb.current {
      border-color: var(--primary-color);
    }
    .thumb img {
      position: relative;
      width: 100%;
      height: 100%;
      object-fit: cover;
      display: block;
    }
    .border {
      display: flex;
      flex-direction: column;
      gap: 6px;
      margin-top: 12px;
    }
    .label {
      font-size: 0.85rem;
      color: var(--secondary-text-color);
    }
    .chips,
    .swatches {
      display: flex;
      flex-wrap: wrap;
      gap: 6px;
    }
    .chip {
      border: 1px solid var(--divider-color);
      border-radius: 14px;
      padding: 4px 10px;
      background: none;
      color: var(--primary-text-color);
      cursor: pointer;
    }
    .chip.selected {
      background: var(--primary-color);
      border-color: var(--primary-color);
      color: var(--text-primary-color, white);
    }
    .swatch {
      width: 24px;
      height: 24px;
      border-radius: 50%;
      border: 2px solid var(--divider-color);
      cursor: pointer;
    }
    .swatch.selected {
      border-color: var(--primary-color);
      box-shadow: 0 0 0 2px var(--card-background-color, white) inset;
    }
    canvas {
      width: 100%;
      display: block;
      border-radius: 6px;
      background: #000;
    }
    canvas.source {
      touch-action: none;
      cursor: grab;
    }
    .zoom {
      display: flex;
      align-items: center;
      gap: 8px;
      margin-top: 6px;
    }
    .zoom input {
      flex: 1;
    }
    .quality {
      display: flex;
      justify-content: space-between;
      gap: 8px;
      font-size: 0.85rem;
      margin-top: 4px;
    }
    .quality.sharp {
      color: var(--success-color, #2e7d32);
    }
    .quality.soft {
      color: var(--warning-color, #e65100);
    }
    .size {
      color: var(--secondary-text-color);
      direction: ltr;
    }
    .actions {
      display: flex;
      justify-content: flex-end;
      gap: 8px;
      margin-top: 12px;
    }
    .actions button,
    .border .primary {
      border: 1px solid var(--divider-color);
      border-radius: 8px;
      padding: 6px 14px;
      background: none;
      color: var(--primary-text-color);
      cursor: pointer;
    }
    button.primary {
      background: var(--primary-color);
      border-color: var(--primary-color);
      color: var(--text-primary-color, white);
    }
    button:disabled {
      opacity: 0.5;
      cursor: default;
    }
    .border .primary {
      align-self: flex-start;
    }
    .hint {
      margin: 6px 0 0;
      font-size: 0.85rem;
      color: var(--secondary-text-color);
    }
  `, customElements.get("samstream-art") || customElements.define("samstream-art", Ge);
//#endregion
//#region src/samstream-card.ts
var Z, Ke = [
	"info",
	"warning",
	"alert"
], qe = 3e3, Je = 400, Ye = 150, Xe = 600, Ze = 1.5, Qe = 16, Q = (e) => e.preventDefault(), $ = class extends V {
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
		let e = (e) => Ne(K(e?.locale?.language ?? e?.language));
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
						options: U.map((t) => ({
							value: t,
							label: e()[et(t)]
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
		return Ne(K(this.hass?.locale?.language ?? this.hass?.language));
	}
	get rtl() {
		return K(this.hass?.locale?.language ?? this.hass?.language) === "ar";
	}
	updated(e) {
		if (!e.has("hass") || !this.hass || !this.config) return;
		let t = `${this.hass.states[this.config.entity]?.attributes.app_id ?? null}|${we(this.hass, this.config.entity)}`;
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
		if (!this.hass || !this.config) return P;
		let e = this.hass.states[this.config.entity];
		if (!e) return M`<ha-card><div class="empty">${this.config.entity}?</div></ha-card>`;
		let t = e.state !== "off" && e.state !== "unavailable", n = Oe(this.config), r = e.attributes.frame_tv === !0, i = (t ? n : n.includes("tv") ? ["tv"] : []).filter((e) => e !== "art" || r);
		return M`
      <ha-card dir=${this.rtl ? "rtl" : "ltr"}>
        ${t || i.length > 0 ? P : this.renderPowerOnly()}
        ${i.map((e, n) => this.renderSection(e, t, n === 0))}
        ${this.feedback ? M`<div class="feedback">${this.feedback}</div>` : P}
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
			touchpad: () => this.renderTouchpad(),
			art: () => M`<samstream-art .hass=${this.hass} .entity=${this.config.entity} .text=${this.text}></samstream-art>`
		}[e]();
		return M`<div class="section ${n ? "first" : ""}">${r}</div>`;
	}
	renderPowerOnly() {
		return M`<div class="power-only">
      <span>${H(this.hass, this.config.entity)} · ${this.text.off}</span>
      ${this.powerButton(!1)}
    </div>`;
	}
	powerButton(e) {
		return M`<button
      class="round ${e ? "on" : ""}"
      title=${this.text.power}
      @click=${() => this.call("media_player", "toggle", { entity_id: this.config.entity })}
    >
      <ha-icon icon="mdi:power"></ha-icon>
    </button>`;
	}
	renderHeader(e) {
		let t = this.text, n = this.hass.states[this.config.entity], r = n.attributes.source ?? "", i = n.attributes.app_id, a = this.apps?.apps.find((e) => e.id === i), o = e ? r === "Home" ? t.home : a?.name ?? r : t.off;
		return M`
      <div class="header">
        ${a ? this.tile(a, "small") : M`<div class="tv"><ha-icon icon="mdi:television"></ha-icon></div>`}
        <div class="titles">
          <div class="name">${H(this.hass, this.config.entity)}</div>
          <div class="sub">${o}</div>
        </div>
        ${this.powerButton(e)}
      </div>
    `;
	}
	renderCameras() {
		let e = this.text, t = Te(this.hass, this.config.cameras);
		if (t.length === 0) return M`<section><h3>${e.cameras}</h3><p class="hint">${e.noCameras}</p></section>`;
		let n = t.includes(this.camera) ? this.camera : t[0];
		return M`
      <section>
        <h3>${e.cameras}</h3>
        <div class="chips">
          ${t.map((e) => M`<button
              class="chip ${e === n ? "selected" : ""}"
              @click=${() => this.camera = e}
            >
              <ha-icon icon="mdi:cctv"></ha-icon>${H(this.hass, e)}
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
		return M`
      <section>
        <h3>${e.message}</h3>
        <input id="notice-title" dir="auto" placeholder=${e.title} />
        <textarea id="notice-message" dir="auto" rows="2" placeholder=${e.messagePlaceholder}></textarea>
        <div class="row">
          <div class="chips">
            ${Ke.map((e) => M`<button
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
		return M`
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
          ${(this.apps?.sources ?? []).map((n) => M`<button
              class="app ${t.attributes.source === n ? "current" : ""}"
              @click=${() => this.selectSource(n)}
            >
              <div class="tile home">
<ha-icon icon=${$e(n)}></ha-icon>
              </div>
              <span>${n === "Live TV" ? e.liveTv : n === "Input list" ? e.inputList : n}</span>
            </button>`)}
          ${(this.apps?.apps ?? []).map((e) => M`<button
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
			return M`<button class="key" title=${n} @pointerdown=${i.down} @pointerup=${i.up} @pointerleave=${i.cancel} @pointercancel=${i.cancel} @contextmenu=${Q}>
        <ha-icon icon=${t}></ha-icon>
      </button>`;
		}, n = this.pressable(() => this.sendKey("KEY_ENTER"), "hold", "KEY_ENTER");
		return M`
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
			return r ? M`<button class="key" title=${n} @pointerdown=${a.down} @pointerup=${a.up} @pointerleave=${a.cancel} @pointercancel=${a.cancel} @contextmenu=${Q}>
            <ha-icon icon=${t}></ha-icon>
          </button>` : M`<button class="key" title=${n} @click=${i}><ha-icon icon=${t}></ha-icon></button>`;
		}, n = this.hass.states[this.config.entity]?.attributes.volume_level, r = typeof n == "number", i = this.volumeDrag ?? (r ? Math.round(n * 100) : 0);
		return M`
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
		return M`
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
		return M`
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
					this.repeatTimer = setInterval(e, Ye);
				}, Je)) : this.holdTimer = setTimeout(() => {
					this.held = !0, n && this.call("samstream", "hold_key", {
						entity_id: this.config.entity,
						key: n,
						seconds: Ze
					}, !1);
				}, Xe);
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
		t.x = e.clientX, t.y = e.clientY, t.travel += Math.abs(n) + Math.abs(r), this.pending.x += n * W, this.pending.y += r * W, !this.flushTimer && !this.pointerBusy && (this.flushTimer = setTimeout(() => this.flushPointer(), Qe));
	}
	touchEnd() {
		let e = this.touch;
		if (this.touch = void 0, !e) return;
		let t = Me(e.travel, Date.now() - e.at);
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
		return e.logo ? M`<div class="tile ${t}"><img src=${e.logo} alt="" loading="lazy" /></div>` : M`<div class="tile ${t} letter" style="background:${De(e.name)}">
      ${Ee(e.name)}
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
		this.feedback = e, clearTimeout(this.feedbackTimer), this.feedbackTimer = setTimeout(() => this.feedback = "", qe);
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
function $e(e) {
	return e.startsWith("HDMI") ? "mdi:video-input-hdmi" : e === "Input list" ? "mdi:import" : "mdi:television-classic";
}
function et(e) {
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
