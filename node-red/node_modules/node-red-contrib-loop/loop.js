module.exports = function (RED) {
    'use strict';

    var vm = require('vm');

    function getContext(node, msg) {
        return new vm.createContext({
            console:console,
            Buffer:Buffer,
            Date: Date,
            RED: { util: RED.util },
            __node__: { id: node.id, name: node.name },
            context: {
                set: function() { node.context().set.apply(node,arguments) },
                get: function() { return node.context().get.apply(node,arguments) },
                keys: function() { return node.context().keys.apply(node,arguments) },
                get global() { return node.context().global },
                get flow() { return node.context().flow }
            },
            flow: {
                set: function() { node.context().flow.set.apply(node,arguments) },
                get: function() { return node.context().flow.get.apply(node,arguments) },
                keys: function() { return node.context().flow.keys.apply(node,arguments) }
            },
            global: {
                set: function() { node.context().global.set.apply(node,arguments) },
                get: function() { return node.context().global.get.apply(node,arguments) },
                keys: function() { return node.context().global.keys.apply(node,arguments) }
            },
            env: {
                get: function(envVar) { var flow = node._flow; return flow.getSetting(envVar) }
            },
            msg: msg
        });
    }

    function LoopNode(n) {
        RED.nodes.createNode(this, n);
        var node = this;

        node.kind = n.kind;

        let kinds = ['fcnt', 'cond', 'enum'];
        node.kindFcnt = kinds.indexOf(node.kind) == 0;
        node.kindCond = kinds.indexOf(node.kind) == 1;
        node.kindEnum = kinds.indexOf(node.kind) == 2;

        if (node.kindFcnt) {
            node.count = n.count;
            node.initial = n.initial;
            node.step = n.step;

        } else if (node.kindCond) {
            node.conditionType = n.conditionType;
            switch (node.conditionType) {
                case 'js':
                    node.condition = new vm.Script(n.condition);
                    break;
                case 'jsonata':
                    try { node.condition = RED.util.prepareJSONataExpression(n.condition, node) }
                    catch(e) { node.error(RED._('loop.error.bad-jsonata') + ': ' + e.message) }
                    break;
                case 're':
                    try { node.condition = new RegExp(n.condition) }
                    catch(e) { node.error(RED._('loop.error.bad-regexp') + ': ' + e.message) }
            }
            node.whenBefore = !(node.whenAfter = n.when === 'after');

        } else if (node.kindEnum) {
            node.enumerationType = n.enumerationType;
            node.enumeration = n.enumeration;
        }

        node.limit = n.limit;
        node.loopPayload = n.loopPayload;
        node.finalPayload = n.finalPayload;

        this.on('input', function (msg) {
            var current = node[msg._msgid];

            // Initialization
            if (current === undefined || msg.command === 'restart') {

                if (current === undefined) {
                    node[msg._msgid] = {'payload': msg.payload, 'restarts': 0, 'total': 0};
                    current = node[msg._msgid];
                } else {
                    current.restarts++;
                    msg.payload = current.payload;
                }

                if (node.kindFcnt) {
                    current.count = node.count ? Number(node.count) : Number(msg.count);
                    current.initial = node.initial ? Number(node.initial) : Number(msg.initial);
                    current.step = node.step ? Number(node.step) : Number(msg.step);

                } else if (node.kindCond) {
                    current.ctx = getContext(node, msg);

                } else if (node.kindEnum) {
                    current.enumeration = RED.util.evaluateNodeProperty(node.enumeration, node.enumerationType, node, msg);
                    if (current.enumeration.constructor.name === 'Map' ||
                        current.enumeration.constructor.name === 'Set' ||
                        (typeof current.enumeration) === 'string' ||
                        current.enumeration instanceof Array ||
                        (ArrayBuffer.isView(current.enumeration) && !(current.enumeration instanceof DataView)))
                    {
                        current.iter = current.enumeration[Symbol.iterator]();
                        current.hasPairs = (current.enumeration.constructor.name === 'Map');
                    } else if ((typeof current.enumeration) === 'object') {
                        current.iter = Object.entries(current.enumeration)[Symbol.iterator]();
                        current.hasPairs = true;
                    } else {
                        node.error(RED._('loop.error.not-iterable'));
                    }
                }

                current.limit = node.limit ? Number(node.limit) : Number(msg.limit);
                current.index = -1;
                current.started = Date.now();;
                node.status({fill: 'blue', shape: 'dot', text: 'looping'});
            }

            // Iteration
            let res;
            let next;

            if (Date.now() - current.started >= current.limit) {
                res = false;
                current.timeout = true;
            } else if (msg.command === 'break') {
                res = false;
            } else if (node.kindFcnt) {
                res = (current.index + 1 < current.count);
            } else if (node.kindEnum) {
                next = current.iter.next();
                res = !next.done;
            } else if (current.index == -1 && node.whenAfter) {
                res = true;
            } else {
                switch (node.conditionType) {
                    case 'js':
                        RED.util.setMessageProperty(msg, 'loop.index', current.index + 1, true);
                        res = node.condition.runInContext(current.ctx);
                        break;
                    case 'jsonata':
                        res = RED.util.evaluateJSONataExpression(node.condition, msg);
                        break;
                    case 're': console.log(node.condition); console.log(msg.payload);
                        res = node.condition.test(msg.payload); console.log("Vysledek: "+res);
                }
            }

            // End of loop output
            if (!res) {

                msg.loop = {
                    'broken': msg.command === 'break',
                    'timeout': current.timeout == true,
                    'passed': {
                        'total': current.total,
                        'last': current.index + 1
                    },
                    'restarts': current.restarts
                }

                if (node.finalPayload == 'final-orig')
                       msg.payload = current.payload;

                delete msg.command;
                delete node[msg._msgid];
                node.status({});
                node.send([msg, undefined]);

            // Step of loop output
            } else {

                current.index++;
                current.total++;
                delete msg.command;

                RED.util.setMessageProperty(msg, 'loop.index', current.index, true);
                if (node.kindFcnt) {
                    current.value = current.index == 0 ? current.initial : current.value + current.step;
                    RED.util.setMessageProperty(msg, 'loop.value', current.value, true);
                    RED.util.setMessageProperty(msg, 'loop.count', current.count, true);
                    RED.util.setMessageProperty(msg, 'loop.initial', current.initial, true);
                    RED.util.setMessageProperty(msg, 'loop.step', current.step, true);
                } else if (node.kindEnum) {
                    RED.util.setMessageProperty(msg, 'loop.enumeration', current.enumeration, true);
                    if (current.hasPairs) {
                        RED.util.setMessageProperty(msg, 'loop.key', next.value[0], true);
                        RED.util.setMessageProperty(msg, 'loop.value', next.value[1], true);
                    } else {
                        RED.util.setMessageProperty(msg, 'loop.value', next.value, true);
                    }
                }
                switch (node.loopPayload) {
                    case 'loop-index':
                        msg.payload = msg.loop.index;
                        break;
                    case 'loop-val':
                        msg.payload = msg.loop.value;
                        break;
                    case 'loop-key':
                        msg.payload = msg.loop.key;
                        break;
                    case 'loop-orig':
                        msg.payload = current.payload;
                    // otherwise keep untouch
                }
                node.send([undefined, msg]);
            }
        });

        this.on('close', function () {
            node.status({});
        });
    }

    RED.nodes.registerType('loop', LoopNode);
}
