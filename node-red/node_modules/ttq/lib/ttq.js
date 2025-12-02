function noop() {};

function TimeTestQueue(options) {
  this.asyncTest = options.asyncTest || false;
  this.test = options.test;
  this.success = options.success || noop;
  this.fail = options.fail || noop;
  this.interval = options.interval || 1000;
  this.queue = [];
  this.loop = null;
  this.context = options.context || null;
}

TimeTestQueue.prototype.done = function() {
  clearInterval(this.loop);
};

TimeTestQueue.prototype.pop = function() {
  return this.queue.pop();
};

TimeTestQueue.prototype.push = function(item) {
  this.queue.push(item);
  if (this.loop === null) this.startTimer();
};

TimeTestQueue.prototype.startTimer = function() {
  this.loop = setTimeout(this.runtest.bind(this), this.interval);
};

TimeTestQueue.prototype.testComplete = function(items, success) {
  if (success) {
    this.success.call(this.context, items);
  } else {
    this.fail.call(this.context, items);
  }
};

TimeTestQueue.prototype.runtest = function() {
  // Copy the array
  var items = this.queue.slice(0);
  
  // Clear our state
  this.queue.length = 0;
  this.loop = null;
  // Run tests
  if (this.asyncTest) {
    this.test.call(this.context, items, this.testComplete.bind(this, items));
  } else {
    this.testComplete(items, this.test.call(this.context, items));
  }
};

module.exports = TimeTestQueue;