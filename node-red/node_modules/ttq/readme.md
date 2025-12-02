ttq
=======

A node.js queue that tests its contents on an interval and calls either a `success` or `fail` function with the current contents of the queue.
  
Install
--------
```
npm install ttq
```

Options
--------
* `asyncTest`: Boolean : Whether the test should pass/listen for a callback
* `test`: Function(Array) : The function that gets passed all queued items every `interval` to determine whether a `success` or `fail` functions get called. Returns a Boolean.
* `success`: Function(Array) : The function that gets passed all queued items if the `test` function returns `true`.
* `fail` : Function(Array) : The function that gets passed all queued items if the `test` function returns `false`.
* `interval` : Number : The time in milliseconds between calls of `test`.
* `context` : Object : The `this` context for all function calls (`success`, `fail`, `test`).

Usage
--------
```javascript
var TTQ = require('ttq');

var ttq = new TTQ({
  test: function(array) {
    return array.length > 1000;
  },
  success: function(array) {
    this.emit('hundred-items', array);
  },
  fail: function(array) {
    // it doesn't matter. it's in the past
  },
  interval: 200,
  context: this
});
```

Methods
-------
### push(item)
Push an item onto the queue.  
  
### pop()
Pop an item off the queue.


License
-------
MIT
