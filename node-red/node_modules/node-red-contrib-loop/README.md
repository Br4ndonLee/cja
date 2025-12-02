# Loops for Node-RED

Creating loops is the commont programming technique. The node-red-contrib-loop node provides support for them in Node-RED.

You can choose between three kinds of loops. The loop with a fixed count of repeatitons, the loop based on evaluating a condition or the loop itearating on an iterable enumeration.

## Common Description

You can control the loop by sending `msg.command` to the input. If it contains a `break` string, the loop will be finished imediately. If it contains a `restart` string, the loop will start again from the first value.

The node has two outputs: *end of loop* and *step of loop*. The first output is used at the end when the loop is left. Connect the second output to the input through your loop processing nodes, i.e. create the loop.

![How to connect loop node](https://gitlab.com/advantech-czech/node-red-contrib-loop/-/raw/1.0.1/images/connection.svg)

Nodes in the processing loop connected to *step of loop* output will get `msg.loop` object with the following property:

* `index` - the counter incremented by 1 from 0

It may contain more properties, but they depend on the kind of loop. See bellow for each loop-kind section. You can select one of the properties to be placed to `msg.payload`. Use the **Loop Payload** property in the editor form for this.

On the *end of loop* output you will get `msg.loop` object with the following properties:

* `broken` - true if the loop has received `break` command
* `timeout` - true if the timeout has expired
* `passed.total` - the total number of passes through the loop, included all restarts
* `passed.last` - number of passes through the loop from the last restart or start
* `restarts` - number of times the loop was restarted

You will also get `msg.payload` on *end of loop* output. It is optional which value it should contain. You can choose between *last payload* from the loop and *original payload* which the node received on the input at the start. Use **End Payload** in the editor form to choose.

You can limit time for loops for all three kinds. Use **Time Limit** in the editor form or `msg.limit` on the fly. Time is specified in milliseconds.

## “Fixed Count” Loop Kind

Use this loop kind when you wan a fixed number of repeatitions with the numeric counter.

![The editor form for fixed count loop kind](https://gitlab.com/advantech-czech/node-red-contrib-loop/-/raw/1.0.1/images/fixed_count.png)

The **Count** field specifies the number of passes through loop. You can omit it and use `msg.count` on the fly.

The **Initial Value** field specifies the value from which the counter should count. You can omit it and use `msg.initial` on the fly.

The **Step Value** field specifies the step increment or decrement for the counter.

Nodes in the processing branch connected to *step of loop* output will get `msg.loop` object with the following additional properties:

* `value` - counter value
* `count` - requested count of passes through the loop
* `initial` - value from which the counter started
* `step` - value used to increment or decrement the counter

## “Condition” Loop Kind

Use this loop kind when you need a loop based on some condition.

![The editor form for condition loop kind](https://gitlab.com/advantech-czech/node-red-contrib-loop/-/raw/1.0.1/images/condition.png)

You need to define the condition in the **Condition** field. You can choose from three languages.

* *JavaScript* - Condition written as code in JavaScript language. Condition evaluation will use the result of the last part. The loop will continue if it is `true`, otherwise the loop will finish. Examples:  
  `msg.payload !== "done"`  
  `roses = global.get("roses"); global.set("roses", ++roses); roses <= 100`  
JavaScript code is executed in the sandbox with a limited environment similar to the **function** node.

* *JSONata* - Condition as a [JSONata](https://jsonata.org/) expression. The loop will continue if the expression is evaluated as `true`, otherwise the loop will finish. Examples:  
  `msg.payload in [1,2,3,5,7,13,21]`  
  `$globalContext("status") or msg.size > 10`
  
* *Regex* - Regular Expression used with test() function aplied to `msg.payload`. The loop will continue if it matches, otherwise the loop will finish. Examples:  
  `file[0-9].txt`  
  `^[a-zA-Z0-9]+: .*`

The next three examples do the same work (test if the string ends with "Z" character) in different languages with different speed:

  `msg.payload.substr(-1) != "Z"`  
  `$substring(msg.payload, -1) != "Z"`  
  `.*[^Z]`

The JavaScript is the fastest and the Regex is the slowest in this case. However, this may be different for more complex expressions. And not everthing is easy or possible to write in each of these languages. For example, Regex is only useful for comparing strings but it is also the best choice for complex search patterns.

You can choose if a condition should be evaluated *befor* or *after* the loop. The difference is in evaluating the condition for the initial values in the first case. Compared to classic programing, the first optinon is “while‥do” loop and the second one is “do‥while” / “repeat‥until” loop.

The `msg.loop` has no additional properties for this loop kind.

## “Enumeration” Loop Kind

Use this loop kind when you want to iterate over some enumeration. It must be iterable, which are the following: Array, Typed Array, Object, Map, Set and String.

![The editor form for enumeration loop kind](https://gitlab.com/advantech-czech/node-red-contrib-loop/-/raw/1.0.1/images/enumeration.png)

You nedd to specify enumeration in the **Enumeration** field as a property of the message, flow or global context. You can also specify it directly as JSON or a normal string.

Nodes in the processing branch connected to the *step of loop* output will get a `msg.loop` object with the following additional properties:

* `value` - iterated item value
* `key` - iterated item key; for general object and Map only
* `enumeration` - object it iterates over

## Usage Examples

The examples are available in the *examples* folder. You can import it directly from Node-RED.

## License

Node is pulished under MIT License. See *LICENSE* file.

