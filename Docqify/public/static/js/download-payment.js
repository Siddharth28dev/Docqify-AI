(function () {
    if (!window.fetch) {
        return;
    }

    const nativeFetch = window.fetch.bind(window);

    function isDownloadRequest(url) {
        if (!url) return false;
        try {
            const parsed = new URL(url, window.location.origin);
            return parsed.pathname === "/download_pdf";
        } catch (error) {
            return false;
        }
    }

    function normalizeHeaders(headers) {
        if (!headers) return {};
        if (headers instanceof Headers) {
            return Object.fromEntries(headers.entries());
        }
        return { ...headers };
    }

    function parseJsonBody(body) {
        if (!body) return null;
        if (typeof body === "string") {
            try {
                return JSON.parse(body);
            } catch (error) {
                return null;
            }
        }
        if (typeof body === "object") {
            return body;
        }
        return null;
    }

    async function parseResponseJson(response) {
        const text = await response.text();
        try {
            return text ? JSON.parse(text) : {};
        } catch (error) {
            return { error: text || "Unexpected response" };
        }
    }

    async function getPaymentConfig(docPath) {
        const response = await nativeFetch(`/payment/config?doc_path=${encodeURIComponent(docPath)}`);
        const payload = await parseResponseJson(response);
        if (!response.ok) {
            throw new Error(payload.error || "Could not load payment configuration");
        }
        return payload;
    }

    async function createOrder(docPath) {
        const response = await nativeFetch("/payment/create-order", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ doc_path: docPath })
        });
        const payload = await parseResponseJson(response);
        if (!response.ok) {
            throw new Error(payload.error || "Could not create Razorpay order");
        }
        return payload;
    }

    async function verifyPayment(docPath, responsePayload) {
        const response = await nativeFetch("/payment/verify", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({
                doc_path: docPath,
                order_id: responsePayload.razorpay_order_id,
                payment_id: responsePayload.razorpay_payment_id,
                signature: responsePayload.razorpay_signature
            })
        });
        const payload = await parseResponseJson(response);
        if (!response.ok) {
            throw new Error(payload.error || "Payment verification failed");
        }
        return payload;
    }

    function openRazorpay(orderData, docPath) {
        return new Promise((resolve, reject) => {
            if (typeof window.Razorpay !== "function") {
                reject(new Error("Razorpay checkout script is not loaded"));
                return;
            }

            let settled = false;
            const rejectOnce = (error) => {
                if (settled) return;
                settled = true;
                reject(error);
            };
            const resolveOnce = (value) => {
                if (settled) return;
                settled = true;
                resolve(value);
            };

            const razorpay = new window.Razorpay({
                key: orderData.key,
                amount: orderData.amount,
                currency: orderData.currency,
                name: "DocqifyAI",
                description: `Download ${orderData.doc_name}`,
                order_id: orderData.order_id,
                theme: { color: "#1459ff" },
                handler: async function (paymentResponse) {
                    try {
                        await verifyPayment(docPath, paymentResponse);
                        resolveOnce(orderData.order_id);
                    } catch (error) {
                        rejectOnce(error);
                    }
                },
                modal: {
                    ondismiss: function () {
                        rejectOnce(new Error("Payment was cancelled"));
                    }
                }
            });

            razorpay.on("payment.failed", function (event) {
                const message = event && event.error && event.error.description
                    ? event.error.description
                    : "Payment failed";
                rejectOnce(new Error(message));
            });

            razorpay.open();
        });
    }

    async function guardedDownload(url, init) {
        const requestInit = init || {};
        const payload = parseJsonBody(requestInit.body);
        if (!payload || !payload.html_content) {
            return nativeFetch(url, requestInit);
        }

        const docPath = window.location.pathname;
        payload.doc_path = docPath;

        const config = await getPaymentConfig(docPath);
        if (config.blocked_reason) {
            throw new Error(config.blocked_reason);
        }
        if (config.requires_payment) {
            if (!config.payment_ready || !config.key_id) {
                throw new Error("Payments are not configured by the admin yet");
            }
            const order = await createOrder(docPath);
            payload.order_id = await openRazorpay(order, docPath);
        }

        const headers = normalizeHeaders(requestInit.headers);
        if (!headers["Content-Type"]) {
            headers["Content-Type"] = "application/json";
        }

        return nativeFetch(url, {
            ...requestInit,
            headers,
            body: JSON.stringify(payload)
        });
    }

    window.fetch = function (input, init) {
        const url = typeof input === "string" ? input : (input && input.url);
        if (!isDownloadRequest(url)) {
            return nativeFetch(input, init);
        }
        return guardedDownload(url, init);
    };
})();
